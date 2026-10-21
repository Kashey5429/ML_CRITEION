from uuid import UUID

from sqlalchemy import func, select, text

from ml_criterion.domain.specs import DiagnosticSpec, spec_hash
from ml_criterion.persistence.models import Experiment, IdempotencyRecord, Job


class ApplicationError(Exception):
    def __init__(self, code: str, status: int):
        self.code, self.status = code, status


def get_experiment(session, experiment_id: UUID, *, lock=False):
    query = select(Experiment).where(Experiment.id == experiment_id)
    if lock:
        query = query.with_for_update()
    experiment = session.scalar(query)
    if experiment is None:
        raise ApplicationError("experiment_not_found", 404)
    return experiment


def create_experiment(session, spec, idempotency_key: str | None):
    data = spec.model_dump(mode="json")
    digest = spec_hash(data)
    if idempotency_key:
        # Transaction-scoped lock serializes concurrent requests for the same key.
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": idempotency_key},
        )
        record = session.get(IdempotencyRecord, idempotency_key)
        if record:
            if record.config_hash != digest:
                raise ApplicationError("idempotency_key_conflict", 409)
            return get_experiment(session, record.experiment_id)
    experiment = Experiment(spec=data, config_hash=digest)
    session.add(experiment)
    session.flush()
    if idempotency_key:
        session.add(
            IdempotencyRecord(key=idempotency_key, config_hash=digest, experiment_id=experiment.id)
        )
    return experiment


def start_experiment(session, experiment_id: UUID, settings):
    experiment = get_experiment(session, experiment_id, lock=True)
    if experiment.status != "draft":
        if experiment.status in {"queued", "preparing", "running", "succeeded"}:
            return experiment
        raise ApplicationError("invalid_transition", 409)
    if experiment.spec["kind"] == "benchmark":
        from ml_criterion.application.benchmarks import enqueue_benchmark

        try:
            enqueue_benchmark(session, experiment)
        except ValueError as exc:
            raise ApplicationError(str(exc), 422) from exc
    else:
        if not settings.enable_diagnostic_jobs:
            raise ApplicationError("diagnostic_jobs_disabled", 422)
        DiagnosticSpec.model_validate(experiment.spec)
        session.add(Job(experiment_id=experiment.id))
    experiment.status = "queued"
    session.flush()
    return experiment


def cancel_experiment(session, experiment_id: UUID):
    experiment = get_experiment(session, experiment_id, lock=True)
    if experiment.status in {"succeeded", "failed", "partial", "cancelled", "interrupted"}:
        return experiment
    experiment.cancel_requested_at = func.now()
    experiment.status = "cancelled" if experiment.status == "draft" else "cancelling"
    session.flush()
    return experiment
