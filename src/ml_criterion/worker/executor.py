"""One attempt per process; parent owns terminal publication and cancellation."""

import json
import sys
import time
from uuid import UUID

import psycopg

from ml_criterion.config import Settings
from ml_criterion.domain.specs import DiagnosticSpec


def main():
    envelope = json.load(sys.stdin)
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

            result = execute(payload, UUID(envelope["attempt_id"]), Settings())
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
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
        elif isinstance(exc, psycopg.Error) and exc.sqlstate:
            code = "bench_sql_" + exc.sqlstate
        print(json.dumps({"ok": False, "error_code": code}))


if __name__ == "__main__":
    main()
