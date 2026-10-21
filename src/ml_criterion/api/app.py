from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from ml_criterion.application.experiments import (
    ApplicationError,
    cancel_experiment,
    create_experiment,
    get_experiment,
    start_experiment,
)
from ml_criterion.config import Settings
from ml_criterion.domain.specs import BenchmarkSpec, DatasetSpec, ExperimentSpec
from ml_criterion.persistence.db import create_sessions
from ml_criterion.persistence.models import (
    Attempt,
    ComparisonCase,
    Dataset,
    DatasetVersion,
    Experiment,
    Job,
    Run,
)


def view(experiment):
    return {
        "id": str(experiment.id),
        "status": experiment.status,
        "spec": experiment.spec,
        "config_hash": experiment.config_hash,
        "created_at": experiment.created_at,
        "cancel_requested_at": experiment.cancel_requested_at,
    }


def create_app(settings: Settings | None = None, sessions=None):
    settings = settings or Settings()
    engine = None
    if sessions is None:
        engine, sessions = create_sessions(settings.metadata_url)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if engine:
            engine.dispose()

    app = FastAPI(title="ML Criterion", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(ApplicationError)
    async def application_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code}})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse(status_code=503, content={"error": {"code": "metadata_unavailable"}})

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        with sessions() as session:
            session.execute(text("SELECT id FROM benchmark_slots WHERE id = 1")).scalar_one()
        return {"status": "ready"}

    @app.get("/api/v1/capabilities")
    def capabilities():
        return {
            "benchmark_execution": True,
            "resource_measurement": ["python_process", "bench_container_cgroup_v2"],
            "recommendation_policy_version": 1,
            "algorithms": ["linear_regression"],
            "backends": ["madlib", "sklearn"],
            "dataset_format": "dense finite float64; no missing values",
            "diagnostic_execution": settings.enable_diagnostic_jobs,
            "bench_validation": "Run ml-criterion preflight against the target database",
        }

    @app.post("/api/v1/experiments", status_code=201)
    def create(
        spec: ExperimentSpec,
        idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None,
    ):
        with sessions.begin() as session:
            return view(create_experiment(session, spec, idempotency_key))

    @app.get("/api/v1/experiments")
    def list_experiments(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
        with sessions() as session:
            return [
                view(e)
                for e in session.scalars(
                    select(Experiment)
                    .order_by(Experiment.created_at.desc(), Experiment.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ]

    @app.get("/api/v1/datasets")
    def list_datasets(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)):
        with sessions() as session:
            return [
                {"id": d.id, "spec": d.spec, "created_at": d.created_at}
                for d in session.scalars(
                    select(Dataset)
                    .order_by(Dataset.created_at.desc(), Dataset.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ]

    @app.get("/api/v1/datasets/{dataset_id}/versions")
    def list_versions(
        dataset_id: UUID, limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        with sessions() as session:
            if session.get(Dataset, dataset_id) is None:
                raise ApplicationError("dataset_not_found", 404)
            return [
                {
                    "id": v.id,
                    "dataset_id": v.dataset_id,
                    "status": v.status,
                    "manifest": v.manifest,
                    "error_code": v.error_code,
                    "created_at": v.created_at,
                }
                for v in session.scalars(
                    select(DatasetVersion)
                    .where(DatasetVersion.dataset_id == dataset_id)
                    .order_by(DatasetVersion.created_at.desc(), DatasetVersion.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ]

    @app.post("/api/v1/experiments/validate")
    def validate(spec: BenchmarkSpec):
        from uuid import uuid4

        from ml_criterion.application.benchmarks import plan_matrix

        with sessions() as session:
            version = session.get(DatasetVersion, spec.dataset_version_id)
            if not version or version.status != "ready":
                raise ApplicationError("dataset_version_not_ready", 422)
            try:
                cases, runs = plan_matrix(uuid4(), spec.model_dump(mode="json"), version.manifest)
            except ValueError as exc:
                raise ApplicationError(str(exc), 422) from exc
            return {
                "cases": len(cases),
                "runs": len(runs),
                "measured_runs": sum(not r["warmup"] for r in runs),
            }

    @app.post("/api/v1/datasets", status_code=201)
    def register_dataset(spec: DatasetSpec):
        if spec.source_schema not in settings.source_schemas:
            raise ApplicationError("source_schema_not_allowed", 422)
        with sessions.begin() as session:
            dataset = Dataset(spec=spec.model_dump(mode="json"))
            session.add(dataset)
            session.flush()
            return {"id": dataset.id, "spec": dataset.spec}

    @app.post("/api/v1/datasets/{dataset_id}/versions", status_code=202)
    def create_version(dataset_id: UUID):
        with sessions.begin() as session:
            dataset = session.get(Dataset, dataset_id)
            if not dataset:
                raise ApplicationError("dataset_not_found", 404)
            version = DatasetVersion(dataset_id=dataset_id)
            session.add(version)
            session.flush()
            session.add(
                Job(
                    kind="snapshot",
                    version_id=version.id,
                    payload={
                        "kind": "snapshot",
                        "source": dataset.spec,
                        "version_id": str(version.id),
                        "timeout_seconds": 300,
                    },
                )
            )
            return {"id": version.id, "status": version.status}

    @app.get("/api/v1/dataset-versions/{version_id}")
    def get_version(version_id: UUID):
        with sessions() as session:
            version = session.get(DatasetVersion, version_id)
            if not version:
                raise ApplicationError("dataset_version_not_found", 404)
            return {
                "id": version.id,
                "dataset_id": version.dataset_id,
                "status": version.status,
                "manifest": version.manifest,
                "error_code": version.error_code,
            }

    @app.get("/api/v1/experiments/{experiment_id}")
    def get(experiment_id: UUID):
        with sessions() as session:
            return view(get_experiment(session, experiment_id))

    @app.post("/api/v1/experiments/{experiment_id}/start", status_code=202)
    def start(experiment_id: UUID):
        with sessions.begin() as session:
            return view(start_experiment(session, experiment_id, settings))

    @app.post("/api/v1/experiments/{experiment_id}/cancel", status_code=202)
    def cancel(experiment_id: UUID):
        with sessions.begin() as session:
            return view(cancel_experiment(session, experiment_id))

    @app.get("/api/v1/experiments/{experiment_id}/attempts")
    def attempts(
        experiment_id: UUID, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
    ):
        with sessions() as session:
            get_experiment(session, experiment_id)
            rows = session.scalars(
                select(Attempt)
                .join(Job)
                .where(Job.experiment_id == experiment_id)
                .order_by(Attempt.started_at, Attempt.id)
                .offset(offset)
                .limit(limit)
            )
            return [
                {
                    "id": str(a.id),
                    "token": a.token,
                    "status": a.status,
                    "started_at": a.started_at,
                    "finished_at": a.finished_at,
                    "error_code": a.error_code,
                    "result": a.result,
                }
                for a in rows
            ]

    @app.get("/api/v1/experiments/{experiment_id}/runs")
    def runs(
        experiment_id: UUID, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
    ):
        with sessions() as session:
            get_experiment(session, experiment_id)
            rows = session.execute(
                select(Run, ComparisonCase)
                .join(ComparisonCase)
                .where(ComparisonCase.experiment_id == experiment_id)
                .order_by(Run.sequence)
                .offset(offset)
                .limit(limit)
            ).all()
            return [
                {
                    "id": run.id,
                    "case_id": case.id,
                    "config": case.config,
                    "backend": run.backend,
                    "repeat_index": run.repeat_index,
                    "pair_id": run.pair_id,
                    "warmup": run.warmup,
                    "sequence": run.sequence,
                    "status": run.status,
                    "result": run.result,
                }
                for run, case in rows
            ]

    @app.get("/api/v1/experiments/{experiment_id}/results")
    def results(experiment_id: UUID):
        from statistics import median

        with sessions() as session:
            experiment = get_experiment(session, experiment_id)
            rows = session.scalars(
                select(Run)
                .join(ComparisonCase)
                .where(ComparisonCase.experiment_id == experiment_id)
                .order_by(Run.sequence)
            ).all()
            groups = {}
            for run in rows:
                if run.warmup or run.status != "succeeded":
                    continue
                key = (str(run.case_id), run.backend)
                groups.setdefault(key, []).append(run.result)
            return {
                "status": experiment.status,
                "total_runs": len(rows),
                "completed_runs": sum(r.status == "succeeded" for r in rows),
                "summary": [
                    {
                        "case_id": case,
                        "backend": backend,
                        "count": len(items),
                        "median_model_wall_ns": median(
                            r["timings"]["model_wall_ns"] for r in items
                        ),
                        "median_rmse": median(r["quality"]["rmse"] for r in items),
                    }
                    for (case, backend), items in groups.items()
                ],
                "analysis": experiment.analysis,
                "note": "Warmups excluded. Paired analysis and case recommendations in analysis.",
            }

    @app.get("/api/v1/experiments/{experiment_id}/recommendation")
    def recommendation(experiment_id: UUID):
        with sessions() as session:
            experiment = get_experiment(session, experiment_id)
            if experiment.analysis is None:
                return {
                    "status": "unavailable",
                    "experiment_status": experiment.status,
                    "reason": "analysis_not_published",
                    "cases": [],
                }
            return {"status": "ready", **experiment.analysis}

    @app.get("/api/v1/experiments/{experiment_id}/report")
    def report(experiment_id: UUID):
        with sessions() as session:
            experiment = get_experiment(session, experiment_id)
            if experiment.analysis is None:
                raise ApplicationError("analysis_not_published", 409)
            return JSONResponse(
                content={
                    "experiment_id": str(experiment.id),
                    "spec": experiment.spec,
                    "config_hash": experiment.config_hash,
                    "analysis": experiment.analysis,
                },
                headers={"Content-Disposition": f'attachment; filename="{experiment_id}.json"'},
            )

    @app.get("/api/v1/attempts/{attempt_id}/artifact")
    def artifact(attempt_id: UUID):
        with sessions() as session:
            attempt = session.get(Attempt, attempt_id)
            if not attempt or attempt.status != "succeeded" or not attempt.result:
                raise ApplicationError("artifact_not_found", 404)
            manifest = attempt.result.get("artifact")
            if not manifest:
                raise ApplicationError("artifact_not_found", 404)
            root = Path(settings.artifact_root).resolve()
            path = (root / manifest["key"]).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ApplicationError("artifact_unavailable", 404)
            return FileResponse(path, media_type="application/json", filename=f"{attempt_id}.json")

    return app
