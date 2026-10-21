from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select

from ml_criterion.application.benchmarks import complete_job
from ml_criterion.persistence.models import (
    Attempt,
    BenchmarkSlot,
    DatasetVersion,
    Experiment,
    Job,
    Run,
)


@dataclass(frozen=True)
class Lease:
    job_id: UUID
    experiment_id: UUID | None
    attempt_id: UUID
    owner: str
    token: int
    spec: dict


class Queue:
    """All mutation paths lock slot -> job -> experiment, in that order."""

    def __init__(self, sessions, lease_seconds=30):
        self.sessions = sessions
        self.lease_seconds = lease_seconds

    def claim(self, owner: str) -> Lease | None:
        with self.sessions.begin() as session:
            slot = session.scalar(
                select(BenchmarkSlot).where(BenchmarkSlot.id == 1).with_for_update(skip_locked=True)
            )
            if slot is None or slot.state != "available":
                return None
            job = session.scalar(
                select(Job)
                .where(Job.state == "queued")
                .order_by(Job.created_at, Job.sequence, Job.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            experiment = (
                session.get(Experiment, job.experiment_id, with_for_update=True)
                if job.experiment_id
                else None
            )
            if experiment and (
                experiment.cancel_requested_at or experiment.status == "interrupted"
            ):
                job.state = "cancelled"
                complete_job(session, job, experiment, "cancelled", None, "cancel_requested")
                return None
            now = session.scalar(select(func.clock_timestamp()))
            job.state, job.owner = "leased", owner
            job.token += 1
            job.lease_until = now + timedelta(seconds=self.lease_seconds)
            if experiment:
                experiment.status = "preparing" if job.kind == "prepare" else "running"
            if job.version_id:
                session.get(DatasetVersion, job.version_id).status = "running"
            if job.run_id:
                session.get(Run, job.run_id).status = "running"
            slot.state, slot.job_id, slot.token = "busy", job.id, job.token
            attempt = Attempt(job_id=job.id, token=job.token)
            session.add(attempt)
            session.flush()
            payload = experiment.spec if job.kind == "diagnostic" else job.payload
            return Lease(job.id, job.experiment_id, attempt.id, owner, job.token, payload)

    def _owned(self, session, lease):
        slot = session.get(BenchmarkSlot, 1, with_for_update=True)
        job = session.get(Job, lease.job_id, with_for_update=True)
        now = session.scalar(select(func.clock_timestamp()))
        if (
            slot.state != "busy"
            or slot.job_id != lease.job_id
            or slot.token != lease.token
            or job.state != "leased"
            or job.owner != lease.owner
            or job.token != lease.token
            or job.lease_until <= now
        ):
            return None
        experiment = (
            session.get(Experiment, job.experiment_id, with_for_update=True)
            if job.experiment_id
            else None
        )
        return slot, job, experiment, now

    def heartbeat(self, lease: Lease) -> str:
        with self.sessions.begin() as session:
            owned = self._owned(session, lease)
            if not owned:
                return "lost"
            _, job, experiment, now = owned
            job.lease_until = now + timedelta(seconds=self.lease_seconds)
            return "cancel" if experiment and experiment.cancel_requested_at else "ok"

    def finish(self, lease: Lease, status: str, result=None, error_code=None) -> bool:
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("Invalid completion status")
        with self.sessions.begin() as session:
            owned = self._owned(session, lease)
            if not owned:
                return False
            slot, job, experiment, now = owned
            if experiment and experiment.cancel_requested_at:
                status, result, error_code = "cancelled", None, "cancel_requested"
            attempt = session.get(Attempt, lease.attempt_id)
            attempt.status, attempt.finished_at = status, now
            attempt.result, attempt.error_code = result, error_code
            job.state = status
            complete_job(session, job, experiment, status, result, error_code)
            job.owner, job.lease_until = None, None
            slot.state, slot.job_id, slot.token = "available", None, None
            return True

    def recover_expired(self) -> bool:
        # A dead supervisor may have left a live child or SQL session. Never blindly reclaim.
        with self.sessions.begin() as session:
            slot = session.get(BenchmarkSlot, 1, with_for_update=True)
            if slot.state != "busy":
                return False
            job = session.get(Job, slot.job_id, with_for_update=True)
            now = session.scalar(select(func.clock_timestamp()))
            if job.lease_until > now:
                return False
            experiment = (
                session.get(Experiment, job.experiment_id, with_for_update=True)
                if job.experiment_id
                else None
            )
            attempt = session.scalar(
                select(Attempt).where(Attempt.job_id == job.id, Attempt.token == job.token)
            )
            attempt.status, attempt.finished_at = "interrupted", now
            attempt.error_code = "lease_expired_unconfirmed_stop"
            job.state, slot.state = "interrupted", "quarantined"
            complete_job(session, job, experiment, "interrupted", None, attempt.error_code)
            if experiment:
                experiment.status = "interrupted"
            return True

    def release_quarantine(self):
        """Operator must first verify the old process/container is stopped."""
        with self.sessions.begin() as session:
            slot = session.get(BenchmarkSlot, 1, with_for_update=True)
            if slot.state != "quarantined":
                raise ValueError("Slot is not quarantined")
            slot.state, slot.job_id, slot.token = "available", None, None
