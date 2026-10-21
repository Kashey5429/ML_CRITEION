import hashlib
import json
import math
import os
import platform
import time
from pathlib import Path

import psycopg
from psycopg import sql
from threadpoolctl import threadpool_info, threadpool_limits

from ml_criterion.backends.base import RunContext
from ml_criterion.backends.madlib import MadlibAdapter
from ml_criterion.backends.sklearn import SklearnAdapter
from ml_criterion.datasets.execution import prepare, snapshot
from ml_criterion.measurement.resources import make_sampler


def evaluate(connection, namespace, expected):
    s = sql.Identifier(namespace)
    rows, missing, extra, invalid, rmse, mae = connection.execute(
        sql.SQL("""
        SELECT count(*), count(*) FILTER (WHERE p.row_id IS NULL),
            count(*) FILTER (WHERE t.row_id IS NULL),
            count(*) FILTER (WHERE p.y_pred IS NULL OR
                p.y_pred = ANY(ARRAY['NaN','Infinity','-Infinity']::float8[])),
            sqrt(avg((p.y_pred-t.y)^2)), avg(abs(p.y_pred-t.y))
        FROM {}.test t FULL JOIN {}.predictions p USING(row_id)
    """).format(s, s)
    ).fetchone()
    if rows != expected or missing or extra or invalid or not all(map(math.isfinite, [rmse, mae])):
        raise ValueError("invalid_predictions")
    return {"rmse": rmse, "mae": mae, "test_rows": rows}


def run_model(connection, payload, attempt_id, settings):
    namespace = "attempt_" + attempt_id.hex
    timings = {}
    context = RunContext(connection, namespace, payload, settings.sklearn_memory_mb)
    adapter = {"madlib": MadlibAdapter, "sklearn": SklearnAdapter}[payload["backend"]]()
    adapter.validate(context)
    connection.commit()
    sampler = make_sampler(settings.bench_dsn, attempt_id, settings.resource_sample_seconds)
    sampling = False
    try:
        with threadpool_limits(limits=payload["threads"]):
            sampler.start()
            sampling = True
            started = time.perf_counter_ns()
            phase = time.perf_counter_ns()
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(namespace)))
            source = payload["prepared"]
            for name, condition in (("train", "is_train"), ("test", "NOT is_train")):
                connection.execute(
                    sql.SQL("CREATE VIEW {}.{} AS SELECT * FROM {}.{} WHERE {}").format(
                        sql.Identifier(namespace),
                        sql.Identifier(name),
                        sql.Identifier(source["schema"]),
                        sql.Identifier(source["table"]),
                        sql.SQL(condition),
                    )
                )
            connection.commit()
            adapter.prepare(context)
            timings["backend_prepare_ns"] = time.perf_counter_ns() - phase
            for name in ("train", "predict", "persist_results"):
                phase = time.perf_counter_ns()
                getattr(adapter, name)(context)
                timings[name + "_ns"] = time.perf_counter_ns() - phase
            timings["model_wall_ns"] = time.perf_counter_ns() - started
            resources = sampler.finish()
            sampling = False
            phase = time.perf_counter_ns()
            quality = evaluate(connection, namespace, source["test_count"])
            timings["evaluate_ns"] = time.perf_counter_ns() - phase
            diagnostics = adapter.collect_diagnostics(context)
            if diagnostics["rows_processed"] != source["train_count"]:
                raise ValueError("training_row_count_mismatch")
            environment = {
                "python": platform.python_version(),
                "threads": payload["threads"],
                "threadpools": threadpool_info(),
                "postgres": connection.execute("SHOW server_version").fetchone()[0],
                "cache_policy": "uncontrolled_warm_cache",
                "postgres_settings": dict(
                    connection.execute(
                        "SELECT name,setting FROM pg_settings WHERE name = ANY(%s)",
                        (
                            [
                                "max_parallel_workers_per_gather",
                                "max_parallel_workers",
                                "work_mem",
                                "shared_buffers",
                                "maintenance_work_mem",
                            ],
                        ),
                    ).fetchall()
                ),
            }
            return {
                "timings": timings,
                "quality": quality,
                "diagnostics": diagnostics,
                "environment": environment,
                "resources": resources,
                "attempt_id": str(attempt_id),
                "predictions": {"schema": namespace, "table": "predictions"},
                "prepared": source,
            }
    finally:
        if sampling:
            sampler.finish()
        for reader in sampler.readers.values():
            if hasattr(reader, "close"):
                reader.close()
        adapter.cleanup()


def execute(payload, attempt_id, settings):
    # Unique application_name allows the parent to stop exactly this attempt's SQL sessions.
    timeout = int(payload.get("timeout_seconds", 300) * 1000)
    with psycopg.connect(
        settings.bench_dsn,
        connect_timeout=5,
        application_name="mlc:" + attempt_id.hex,
        options=f"-cstatement_timeout={timeout} -clock_timeout=5000",
    ) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        if payload["kind"] == "snapshot":
            result = snapshot(connection, payload, attempt_id, settings)
        elif payload["kind"] == "prepare":
            result = prepare(connection, payload, attempt_id)
        else:
            result = run_model(connection, payload, attempt_id, settings)
        connection.commit()
    if payload["kind"] == "run":
        root = Path(settings.artifact_root) / attempt_id.hex
        root.mkdir(parents=True, exist_ok=True)
        raw = json.dumps({"spec": payload, **result}, sort_keys=True, allow_nan=False).encode()
        temporary = root / "result.tmp"
        with temporary.open("wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(root / "result.json")
        result["artifact"] = {
            "key": f"{attempt_id.hex}/result.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
        }
    return result
