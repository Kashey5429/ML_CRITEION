import argparse
import json
import logging
import signal

from ml_criterion.config import Settings
from ml_criterion.persistence.db import create_sessions
from ml_criterion.worker.queue import Queue
from ml_criterion.worker.supervisor import Supervisor


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "level": record.levelname,
                "event": record.getMessage(),
                "job_id": getattr(record, "job_id", None),
            }
        )


def main():
    parser = argparse.ArgumentParser(prog="ml-criterion")
    sub = parser.add_subparsers(dest="command", required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    sub.add_parser("preflight")
    release = sub.add_parser("release-quarantine")
    release.add_argument(
        "--confirmed-stopped",
        required=True,
        action="store_true",
        help="Assert old executor/container has been stopped and inspected",
    )
    args = parser.parse_args()
    settings = Settings()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    if args.command == "preflight":
        from ml_criterion.preflight import check_stand

        try:
            result = check_stand(settings.bench_dsn)
        except Exception as exc:
            # Don't expose connection strings, user data, or SQL parameters in CLI diagnostics.
            print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
            raise SystemExit(1) from None
        print(json.dumps(result, indent=2))
        return
    engine, sessions = create_sessions(settings.metadata_url)
    try:
        if args.command == "release-quarantine":
            Queue(sessions).release_quarantine()
            return
        supervisor = Supervisor(sessions, settings)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: supervisor.stop.set())
        supervisor.run(once=args.once)
    finally:
        engine.dispose()
