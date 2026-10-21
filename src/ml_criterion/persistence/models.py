from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    spec: Mapped[dict] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis: Mapped[dict | None] = mapped_column(JSONB)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    config_hash: Mapped[str] = mapped_column(String(64))
    experiment_id: Mapped[UUID] = mapped_column(ForeignKey("experiments.id"))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    experiment_id: Mapped[UUID | None] = mapped_column(ForeignKey("experiments.id"))
    version_id: Mapped[UUID | None] = mapped_column(ForeignKey("dataset_versions.id"))
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("runs.id"), unique=True)
    kind: Mapped[str] = mapped_column(String(24), default="diagnostic", server_default="diagnostic")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    sequence: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    state: Mapped[str] = mapped_column(String(24), default="queued")
    owner: Mapped[str | None] = mapped_column(String(64))
    token: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_jobs_state_created", "state", "created_at"),)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    token: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("job_id", "token"),)


class BenchmarkSlot(Base):
    __tablename__ = "benchmark_slots"
    id: Mapped[int] = mapped_column(primary_key=True)
    state: Mapped[str] = mapped_column(String(24), default="available")
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id"))
    token: Mapped[int | None] = mapped_column(Integer)


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    spec: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id"))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    manifest: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ComparisonCase(Base):
    __tablename__ = "comparison_cases"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    experiment_id: Mapped[UUID] = mapped_column(ForeignKey("experiments.id"))
    case_index: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSONB)
    prepared: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("experiment_id", "case_index"),)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("comparison_cases.id"))
    backend: Mapped[str] = mapped_column(String(16))
    repeat_index: Mapped[int] = mapped_column(Integer)
    warmup: Mapped[bool] = mapped_column(Boolean)
    pair_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("case_id", "backend", "repeat_index", "warmup"),)
