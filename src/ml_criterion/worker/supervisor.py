import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

import psutil

from ml_criterion.domain.specs import DiagnosticSpec
from ml_criterion.worker.cancellation import stop_bench_sessions
from ml_criterion.worker.queue import Queue

log = logging.getLogger(__name__)


def stop_process(process):
    """Return only after the process tree has stopped, otherwise raise."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)
    else:
        try:
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            for item in [*children, parent]:
                try:
                    item.terminate()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs([*children, parent], timeout=3)
            for item in alive:
                item.kill()
            _, alive = psutil.wait_procs(alive, timeout=3)
            if alive:
                raise RuntimeError("Could not stop executor tree")
        except psutil.NoSuchProcess:
            pass
        process.wait(timeout=3)


class Supervisor:
    def __init__(self, sessions, settings):
        self.settings = settings
        self.queue = Queue(sessions, settings.lease_seconds)
        self.owner = str(uuid4())
        self.stop = threading.Event()

    def execute(self, lease):
        diagnostic = lease.spec["kind"] == "diagnostic"
        if diagnostic:
            DiagnosticSpec.model_validate(lease.spec)
            if not self.settings.enable_diagnostic_jobs:
                self.queue.finish(lease, "failed", error_code="unsupported_job")
                return
        environment = os.environ.copy()
        environment.update(
            {
                "ML_BENCH_DSN": self.settings.bench_dsn,
                "ML_ARTIFACT_ROOT": self.settings.artifact_root,
                "ML_SOURCE_SCHEMAS": json.dumps(self.settings.source_schemas),
                "ML_MAX_DATASET_ROWS": str(self.settings.max_dataset_rows),
                "ML_SKLEARN_MEMORY_MB": str(self.settings.sklearn_memory_mb),
                "ML_RESOURCE_SAMPLE_SECONDS": str(self.settings.resource_sample_seconds),
            }
        )
        timeout = lease.spec.get("timeout_seconds", 300)
        # A file avoids pipe deadlock for large prepared-dataset manifests.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
            process = subprocess.Popen(
                [sys.executable, "-m", "ml_criterion.worker.executor"],
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=subprocess.DEVNULL,
                text=True,
                env=environment,
                start_new_session=(os.name == "posix"),
            )
            status, result, code = "failed", None, "executor_failed"
            lost = False
            try:
                process.stdin.write(
                    json.dumps({"payload": lease.spec, "attempt_id": str(lease.attempt_id)})
                )
                process.stdin.close()
                started = time.monotonic()
                next_heartbeat = started
                while True:
                    now = time.monotonic()
                    if now >= next_heartbeat:
                        state = self.queue.heartbeat(lease)
                        if state != "ok":
                            lost = state == "lost"
                            status, code = "cancelled", "cancel_requested"
                            break
                        next_heartbeat = now + self.settings.heartbeat_seconds
                    if self.stop.is_set() or now - started >= timeout:
                        code = "worker_shutdown" if self.stop.is_set() else "executor_timeout"
                        break
                    if process.poll() is not None:
                        if process.returncode == 0:
                            output.seek(0)
                            message = json.loads(output.read(2 * 1024**2))
                            if message["ok"]:
                                status, result, code = "succeeded", message["result"], None
                            else:
                                code = message["error_code"]
                        break
                    self.stop.wait(0.1)
            finally:
                stop_process(process)
                if not process.stdin.closed:
                    process.stdin.close()
                if not diagnostic:
                    # Failure to confirm SQL termination leaves the lease for quarantine.
                    stop_bench_sessions(self.settings.bench_dsn, lease.attempt_id)
            if not lost:
                self.queue.finish(lease, status, result=result, error_code=code)

    def run(self, once=False):
        while not self.stop.is_set():
            try:
                self.queue.recover_expired()
                lease = self.queue.claim(self.owner)
                if lease:
                    log.info("job_started", extra={"job_id": str(lease.job_id)})
                    self.execute(lease)
            except Exception:
                # Avoid logging database exception strings that may contain connection details.
                log.error("worker_iteration_failed")
                if once:
                    raise
            if once:
                return
            self.stop.wait(self.settings.poll_seconds)
