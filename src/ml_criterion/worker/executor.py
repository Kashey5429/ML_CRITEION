"""Sequential attempts may share a process; parent owns publication and cancellation."""

import json
import sys
import time
from uuid import UUID

import psycopg

from ml_criterion.config import Settings
from ml_criterion.domain.specs import DiagnosticSpec


def handle(envelope, connection=None):
    payload = envelope["payload"]
    try:
        if payload["kind"] == "diagnostic":
            spec = DiagnosticSpec.model_validate(payload)
            started = time.perf_counter_ns()
            if spec.mode == "hang":
                while True:
                    time.sleep(60)
            time.sleep(spec.duration_seconds)
            if spec.mode == "fail":
                raise ValueError("diagnostic_failure")
            result = {"kind": "diagnostic", "elapsed_ns": time.perf_counter_ns() - started}
        else:
            from ml_criterion.worker.benchmark import execute

            result = execute(
                payload, UUID(envelope["attempt_id"]), Settings(), connection=connection
            )
        print(json.dumps({"ok": True, "result": result}, allow_nan=False), flush=True)
    except Exception as exc:
        code = "executor_failed"
        allowed = {
            "source_schema_not_allowed",
            "source_must_be_a_table",
            "features_and_target_must_be_numeric",
            "unsupported_row_id_type",
            "null_or_nonfinite_data",
            "dataset_row_limit",
            "unsupported_madlib_version",
            "sklearn_memory_budget_exceeded",
            "invalid_predictions",
            "training_row_count_mismatch",
        }
        if isinstance(exc, ValueError) and str(exc) in allowed:
            code = str(exc)
        elif payload["kind"] == "import" and isinstance(exc, ValueError):
            code = str(exc)[:500]
        elif isinstance(exc, psycopg.Error) and exc.sqlstate:
            code = "bench_sql_" + exc.sqlstate
        print(json.dumps({"ok": False, "error_code": code}), flush=True)


def main():
    if "--persistent" not in sys.argv:
        handle(json.load(sys.stdin))
        return
    settings = Settings()
    with psycopg.connect(settings.bench_dsn, connect_timeout=5) as connection:
        for line in sys.stdin:
            handle(json.loads(line), connection)
            connection.rollback()


if __name__ == "__main__":
    main()
