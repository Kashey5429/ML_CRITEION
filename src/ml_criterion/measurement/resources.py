import threading
import time
from pathlib import Path

import psutil
import psycopg


class ProcessReader:
    def __init__(self):
        self.process = psutil.Process()
        self.counters = {}
        self.limits = {}
        try:
            quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
            memory = Path("/sys/fs/cgroup/memory.max").read_text().strip()
            self.limits = {
                "cpu_limit_cores": None if quota == "max" else int(quota) / int(period),
                "memory_limit_bytes": None if memory == "max" else int(memory),
            }
        except (OSError, ValueError):
            pass

    def read(self):
        rss = 0
        for process in [self.process, *self.process.children(recursive=True)]:
            with process.oneshot():
                identity = (process.pid, process.create_time())
                cpu = process.cpu_times()
                self.counters[identity] = cpu.user + cpu.system
                rss += process.memory_info().rss
        return {
            "status": "available",
            "cpu_seconds": sum(self.counters.values()),
            "memory_bytes": rss,
            "identity": "executor-tree",
            **self.limits,
        }


class DatabaseReader:
    def __init__(self, dsn, attempt_id):
        self.connection = psycopg.connect(
            dsn,
            connect_timeout=2,
            autocommit=True,
            application_name="mlc:" + attempt_id.hex,
            options="-cstatement_timeout=1000",
        )

    def read(self):
        snapshot, started = self.connection.execute(
            "SELECT criterion_monitor.snapshot(), pg_postmaster_start_time()::text"
        ).fetchone()
        snapshot["identity"] = snapshot.get("identity", "") + ":" + started
        return snapshot

    def close(self):
        self.connection.close()


class ResourceSampler:
    """Boundary samples plus periodic observations; missing counters are never zero."""

    def __init__(self, readers, interval_seconds=0.1):
        self.readers = readers
        self.interval = interval_seconds
        self.samples = {name: {"count": 0, "valid": True} for name in readers}
        self.errors = {name: 0 for name in readers}
        self.reasons = {}
        self.stop_event = threading.Event()
        self.read_seconds = 0.0
        self.max_gap = 0.0
        self.last_sample = None
        self.delayed_intervals = 0

    def sample(self):
        now = time.perf_counter()
        if self.last_sample is not None:
            self.max_gap = max(self.max_gap, now - self.last_sample)
            self.delayed_intervals += max(0, int((now - self.last_sample) / self.interval) - 1)
        self.last_sample = now
        for name, reader in self.readers.items():
            try:
                data = reader.read()
                if data["status"] != "available":
                    raise ValueError(data.get("reason", "unavailable"))
                summary = self.samples[name]
                if summary["count"] == 0:
                    summary["first"] = data
                    summary["peak"] = data["memory_bytes"]
                else:
                    previous = summary["last"]
                    summary["valid"] &= (
                        data["identity"] == previous["identity"]
                        and data["cpu_seconds"] >= previous["cpu_seconds"]
                    )
                summary["peak"] = max(summary["peak"], data["memory_bytes"])
                summary["last"] = data
                summary["count"] += 1
            except (OSError, ValueError, psutil.Error, psycopg.Error):
                self.errors[name] += 1
                self.reasons[name] = "counter_read_failed"
        self.read_seconds += time.perf_counter() - now

    def start(self):
        self.started = time.perf_counter()
        self.sample()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return self

    def _loop(self):
        while not self.stop_event.wait(self.interval):
            self.sample()

    def finish(self):
        self.stop_event.set()
        self.thread.join()  # SQL reader has a server-side timeout.
        self.sample()
        elapsed = time.perf_counter() - self.started
        scopes = {}
        for name, summary in self.samples.items():
            valid = summary["count"] >= 2 and not self.errors[name] and summary["valid"]
            scopes[name] = {
                "status": "available" if valid else "unavailable",
                "reason": None if valid else self.reasons.get(name, "counter_reset_or_missing"),
                "cpu_seconds": summary["last"]["cpu_seconds"] - summary["first"]["cpu_seconds"]
                if valid
                else None,
                "peak_memory_bytes": summary["peak"] if valid else None,
                "baseline_memory_bytes": summary["first"]["memory_bytes"] if valid else None,
                "samples": summary["count"],
                "missed_samples": self.errors[name],
                "limits": {
                    key: summary.get("first", {}).get(key)
                    for key in ("cpu_limit_cores", "memory_limit_bytes")
                },
            }
        return {
            "version": 1,
            "phase": "model",
            "interval_seconds": self.interval,
            "window_seconds": elapsed,
            "max_sample_gap_seconds": self.max_gap,
            "delayed_intervals": self.delayed_intervals,
            "sampler_read_seconds": self.read_seconds,
            "scopes": scopes,
            "notes": [
                "python_process: summed RSS and CPU of observed executor tree; includes sampler.",
                "Python limits describe the worker container, shared with its supervisor.",
                "bench_container: cgroup v2 CPU and memory.current; includes background and cache.",
                "Memory peaks are sampled lower bounds. Memory scopes are not summed.",
                "Resource window brackets model_wall and includes boundary-read overhead.",
                "Short-lived children may be missed; shared RSS may be counted twice.",
            ],
        }


class UnavailableReader:
    def read(self):
        return {"status": "unavailable"}


def make_sampler(dsn, attempt_id, interval):
    try:
        database = DatabaseReader(dsn, attempt_id)
    except psycopg.Error:
        database = UnavailableReader()
    return ResourceSampler(
        {"python_process": ProcessReader(), "bench_container": database}, interval
    )
