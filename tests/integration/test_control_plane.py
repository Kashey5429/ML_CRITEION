import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from ml_criterion.api.app import create_app
from ml_criterion.config import Settings
from ml_criterion.persistence.models import Attempt, BenchmarkSlot, Experiment, Job
from ml_criterion.worker.queue import Queue
from ml_criterion.worker.supervisor import Supervisor

pytestmark = pytest.mark.integration


@pytest.fixture
def sessions():
    url = os.environ.get("TEST_METADATA_URL")
    if not url:
        pytest.skip("Set TEST_METADATA_URL to run against PostgreSQL")
    # Unique schema: never truncate or drop the application's tables.
    schema = "test_" + uuid4().hex
    admin = create_engine(url, connect_args={"connect_timeout": 5})
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema}", "connect_timeout": 5}
    )
    try:
        with engine.begin() as conn:
            config = Config("alembic.ini")
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def settings():
    return Settings(enable_diagnostic_jobs=True, heartbeat_seconds=0.2, lease_seconds=3)


@pytest.fixture
def client(sessions, settings):
    with TestClient(create_app(settings, sessions)) as client:
        yield client


def enqueue(client, **kwargs):
    response = client.post("/api/v1/experiments", json={"kind": "diagnostic", **kwargs})
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    assert client.post(f"/api/v1/experiments/{identifier}/start").status_code == 202
    return identifier


def test_create_idempotency_and_start(client, sessions):
    headers = {"Idempotency-Key": "same"}
    data = {"kind": "diagnostic", "duration_seconds": 0}
    one = client.post("/api/v1/experiments", json=data, headers=headers)
    two = client.post("/api/v1/experiments", json=data, headers=headers)
    assert one.json()["id"] == two.json()["id"]
    assert (
        client.post(
            "/api/v1/experiments", json={**data, "mode": "fail"}, headers=headers
        ).status_code
        == 409
    )
    identifier = one.json()["id"]
    for _ in range(2):
        assert client.post(f"/api/v1/experiments/{identifier}/start").status_code == 202
    with sessions() as session:
        assert len(session.scalars(select(Job)).all()) == 1


@pytest.mark.parametrize(
    "mode,expected", [("success", "succeeded"), ("fail", "failed"), ("hang", "failed")]
)
def test_real_subprocess(client, sessions, settings, mode, expected):
    identifier = enqueue(client, mode=mode, duration_seconds=0, timeout_seconds=2)
    Supervisor(sessions, settings).run(once=True)
    assert client.get(f"/api/v1/experiments/{identifier}").json()["status"] == expected
    attempts = client.get(f"/api/v1/experiments/{identifier}/attempts").json()
    assert len(attempts) == 1
    if mode == "hang":
        assert attempts[0]["error_code"] == "executor_timeout"
    if mode == "success":
        assert attempts[0]["result"]["kind"] == "diagnostic"


def test_two_workers_only_one_claim(client, sessions):
    enqueue(client)
    queue = Queue(sessions)
    with ThreadPoolExecutor(2) as pool:
        leases = list(pool.map(queue.claim, ["worker-a", "worker-b"]))
    assert sum(lease is not None for lease in leases) == 1


def test_fencing_and_expired_lease_quarantine(client, sessions):
    enqueue(client)
    queue = Queue(sessions)
    lease = queue.claim("worker")
    assert not queue.finish(replace(lease, token=lease.token + 1), "succeeded")
    with sessions.begin() as session:
        session.execute(text("UPDATE jobs SET lease_until = now() - interval '1 second'"))
    assert queue.heartbeat(lease) == "lost"
    assert not queue.finish(lease, "succeeded")
    assert queue.recover_expired()
    assert queue.claim("other") is None
    with sessions() as session:
        assert session.get(BenchmarkSlot, 1).state == "quarantined"
        assert session.get(Attempt, lease.attempt_id).status == "interrupted"
    queue.release_quarantine()


def test_cancel_before_claim(client, sessions):
    identifier = enqueue(client)
    client.post(f"/api/v1/experiments/{identifier}/cancel")
    assert Queue(sessions).claim("worker") is None
    assert client.get(f"/api/v1/experiments/{identifier}").json()["status"] == "cancelled"


def test_cancel_wins_publication_race(client, sessions):
    identifier = enqueue(client)
    queue = Queue(sessions)
    lease = queue.claim("worker")
    client.post(f"/api/v1/experiments/{identifier}/cancel")
    assert queue.finish(lease, "succeeded", result={"must_not_publish": True})
    with sessions() as session:
        assert session.get(Experiment, UUID(identifier)).status == "cancelled"
        assert session.get(Attempt, lease.attempt_id).result is None


def test_benchmark_cannot_silently_run_diagnostic(client):
    data = {"kind": "benchmark", "dataset_version_id": str(uuid4())}
    identifier = client.post("/api/v1/experiments", json=data).json()["id"]
    assert client.post(f"/api/v1/experiments/{identifier}/start").status_code == 422


def test_cancel_running_process(client, sessions, settings):
    identifier = enqueue(client, mode="hang", timeout_seconds=20)
    supervisor = Supervisor(sessions, settings)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(supervisor.run, True)
        deadline = time.monotonic() + 5
        while client.get(f"/api/v1/experiments/{identifier}").json()["status"] != "running":
            assert time.monotonic() < deadline
            time.sleep(0.05)
        client.post(f"/api/v1/experiments/{identifier}/cancel")
        future.result(timeout=5)
    assert client.get(f"/api/v1/experiments/{identifier}").json()["status"] == "cancelled"
    with sessions() as session:
        assert session.get(BenchmarkSlot, 1).state == "available"


def test_health_ready_and_migration_roundtrip(client, sessions):
    assert client.get("/health/ready").status_code == 200
    with sessions.kw["bind"].begin() as conn:
        config = Config("alembic.ini")
        config.attributes["connection"] = conn
        command.check(config)
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    assert client.get("/health/ready").status_code == 200


def test_frontend_history_endpoints(client):
    for n in range(3):
        client.post("/api/v1/experiments", json={"kind": "diagnostic", "duration_seconds": n})
    first = client.get("/api/v1/experiments?limit=2").json()
    second = client.get("/api/v1/experiments?limit=2&offset=2").json()
    assert len(first) == 2 and len(second) == 1
    assert len({e["id"] for e in first + second}) == 3
    assert first[0]["created_at"] >= first[1]["created_at"]
    dataset = client.post(
        "/api/v1/datasets",
        json={
            "name": "source",
            "source_table": "not_materialized",
            "id_column": "id",
            "features": ["x"],
            "target": "y",
        },
    ).json()
    assert client.get("/api/v1/datasets").json()[0]["id"] == dataset["id"]
    version = client.post(f"/api/v1/datasets/{dataset['id']}/versions").json()
    versions = client.get(f"/api/v1/datasets/{dataset['id']}/versions").json()
    assert versions[0]["id"] == version["id"] and versions[0]["status"] == "queued"
    assert client.get(f"/api/v1/datasets/{uuid4()}/versions").status_code == 404
    assert client.get("/api/v1/experiments?limit=101").status_code == 422


@pytest.fixture
def bench_settings(settings, tmp_path):
    dsn = os.environ.get("TEST_BENCH_DSN")
    if not dsn:
        pytest.skip("Set TEST_BENCH_DSN for actual MADlib/sklearn tests")
    return settings.model_copy(
        update={
            "bench_dsn": dsn,
            "artifact_root": str(tmp_path),
            "lease_seconds": 30,
            "heartbeat_seconds": 1,
        }
    )


@pytest.fixture
def source(bench_settings, sessions):
    import psycopg
    from psycopg import sql

    table = "source_" + uuid4().hex
    with psycopg.connect(bench_settings.bench_dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL(
                "CREATE TABLE public.{} AS SELECT i AS id, i::float8 AS x1, "
                "(i%7)::float8 AS x2,(3+2*i-4*(i%7))::float8 AS y "
                "FROM generate_series(1,100) i"
            ).format(sql.Identifier(table))
        )
        yield table
        # Only objects owned by this test's metadata schema are cleaned up.
        with sessions() as session:
            for attempt in session.scalars(select(Attempt)):
                for prefix in ("attempt_", "prep_"):
                    conn.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier(prefix + attempt.id.hex)
                        )
                    )
                conn.execute(
                    sql.SQL("DROP TABLE IF EXISTS snapshots.{}").format(
                        sql.Identifier("v_" + attempt.id.hex)
                    )
                )
        conn.execute(sql.SQL("DROP TABLE public.{}").format(sql.Identifier(table)))


def make_version(client, supervisor, table):
    response = client.post(
        "/api/v1/datasets",
        json={
            "name": "synthetic",
            "source_table": table,
            "id_column": "id",
            "features": ["x1", "x2"],
            "target": "y",
        },
    )
    assert response.status_code == 201, response.text
    dataset = response.json()["id"]
    version = client.post(f"/api/v1/datasets/{dataset}/versions").json()["id"]
    supervisor.run(once=True)
    state = client.get(f"/api/v1/dataset-versions/{version}").json()
    assert state["status"] == "ready", state
    return dataset, version, state["manifest"]


def test_benchmark_matrix_and_immutable_version(sessions, bench_settings, source):
    import psycopg
    from psycopg import sql

    supervisor = Supervisor(sessions, bench_settings)
    with TestClient(create_app(bench_settings, sessions)) as client:
        dataset, version, manifest = make_version(client, supervisor, source)
        with psycopg.connect(bench_settings.bench_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("UPDATE public.{} SET y=y+1000").format(sql.Identifier(source)))
        newer = client.post(f"/api/v1/datasets/{dataset}/versions").json()["id"]
        supervisor.run(once=True)
        assert (
            client.get(f"/api/v1/dataset-versions/{newer}").json()["manifest"]["checksum"]
            != manifest["checksum"]
        )
        spec = {
            "kind": "benchmark",
            "dataset_version_id": version,
            "sample_sizes": [50, None],
            "repeats": 2,
            "warmups": 1,
        }
        assert client.post("/api/v1/experiments/validate", json=spec).json()["runs"] == 12
        identifier = client.post("/api/v1/experiments", json=spec).json()["id"]
        response = client.post(f"/api/v1/experiments/{identifier}/start")
        assert response.status_code == 202, response.text
        for _ in range(13):
            supervisor.run(once=True)
        state = client.get(f"/api/v1/experiments/{identifier}").json()
        attempts = client.get(f"/api/v1/experiments/{identifier}/attempts").json()
        assert state["status"] == "succeeded", attempts
        runs = client.get(f"/api/v1/experiments/{identifier}/runs").json()
        assert len(runs) == 12
        assert all(r["result"]["quality"]["rmse"] < 1e-7 for r in runs)
        for run in runs:
            resources = run["result"]["resources"]
            assert resources["window_seconds"] >= run["result"]["timings"]["model_wall_ns"] / 1e9
            for scope in ("python_process", "bench_container"):
                sample = resources["scopes"][scope]
                assert sample["status"] == "available", sample
                assert sample["cpu_seconds"] >= 0
                assert sample["peak_memory_bytes"] > 0
                assert sample["samples"] >= 2
        pairs = {}
        for run in runs:
            pairs.setdefault(run["pair_id"], []).append(run)
        assert all(len(pair) == 2 for pair in pairs.values())
        for pair in pairs.values():
            assert pair[0]["result"]["prepared"] == pair[1]["result"]["prepared"]
        summary = client.get(f"/api/v1/experiments/{identifier}/results").json()
        assert all(s["count"] == 2 for s in summary["summary"])
        analysis = client.get(f"/api/v1/experiments/{identifier}/recommendation").json()
        assert analysis["status"] == "ready"
        assert len(analysis["cases"]) == 2
        assert all(c["statistics"]["pairs"] == 2 for c in analysis["cases"])
        assert all(c["verdict"] == "inconclusive" for c in analysis["cases"])
        assert all("insufficient_pairs" in c["reasons"] for c in analysis["cases"])
        assert (
            client.get(f"/api/v1/experiments/{identifier}/report").json()["analysis"]
            == summary["analysis"]
        )
        for attempt in attempts:
            if attempt["result"] and "artifact" in attempt["result"]:
                assert client.get(f"/api/v1/attempts/{attempt['id']}/artifact").status_code == 200


def test_snapshot_rejects_invalid_data(sessions, bench_settings, source):
    import psycopg
    from psycopg import sql

    with psycopg.connect(bench_settings.bench_dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL("UPDATE public.{} SET x1=NULL WHERE id=1").format(sql.Identifier(source))
        )
    supervisor = Supervisor(sessions, bench_settings)
    with TestClient(create_app(bench_settings, sessions)) as client:
        dataset = client.post(
            "/api/v1/datasets",
            json={
                "name": "bad",
                "source_table": source,
                "id_column": "id",
                "features": ["x1", "x2"],
                "target": "y",
            },
        ).json()["id"]
        version = client.post(f"/api/v1/datasets/{dataset}/versions").json()["id"]
        supervisor.run(once=True)
        state = client.get(f"/api/v1/dataset-versions/{version}").json()
        assert state["status"] == "failed"
        assert state["error_code"] == "null_or_nonfinite_data"


def test_bench_cancellation_terminates_only_owned_session(bench_settings):
    import threading

    import psycopg

    from ml_criterion.worker.cancellation import stop_bench_sessions

    attempt = uuid4()
    with psycopg.connect(
        bench_settings.bench_dsn, autocommit=True, application_name="mlc:" + attempt.hex
    ) as owned:
        with psycopg.connect(bench_settings.bench_dsn, autocommit=True) as unrelated:
            ready = threading.Event()

            def sleep_query():
                ready.set()
                try:
                    owned.execute("SELECT pg_sleep(30)")
                except psycopg.Error:
                    pass

            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(sleep_query)
                assert ready.wait(2)
                stop_bench_sessions(bench_settings.bench_dsn, attempt)
                future.result(timeout=3)
            assert unrelated.execute("SELECT 1").fetchone() == (1,)


def test_no_intercept_and_cancel_prepared_matrix(sessions, bench_settings, source):
    supervisor = Supervisor(sessions, bench_settings)
    with TestClient(create_app(bench_settings, sessions)) as client:
        _, version, _ = make_version(client, supervisor, source)
        spec = {
            "kind": "benchmark",
            "dataset_version_id": version,
            "fit_intercepts": [False],
            "repeats": 1,
            "warmups": 0,
        }
        identifier = client.post("/api/v1/experiments", json=spec).json()["id"]
        client.post(f"/api/v1/experiments/{identifier}/start")
        for _ in range(3):
            supervisor.run(once=True)
        runs = client.get(f"/api/v1/experiments/{identifier}/runs").json()
        assert all(r["status"] == "succeeded" for r in runs), runs
        assert (
            abs(runs[0]["result"]["quality"]["rmse"] - runs[1]["result"]["quality"]["rmse"]) < 1e-7
        )
        assert runs[1]["result"]["diagnostics"]["intercept"] == 0.0
        cancelled = client.post("/api/v1/experiments", json=spec).json()["id"]
        client.post(f"/api/v1/experiments/{cancelled}/start")
        supervisor.run(once=True)  # Prepare completed; no models trained yet.
        client.post(f"/api/v1/experiments/{cancelled}/cancel")
        supervisor.run(once=True)
        supervisor.run(once=True)
        assert client.get(f"/api/v1/experiments/{cancelled}").json()["status"] == "cancelled"
        runs = client.get(f"/api/v1/experiments/{cancelled}/runs").json()
        assert all(r["status"] == "cancelled" and r["result"] is None for r in runs)
