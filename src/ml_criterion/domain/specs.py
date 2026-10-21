import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


class StrictSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1


class RecommendationPolicy(StrictSpec):
    policy_version: Literal[1] = 1
    min_pairs: int = Field(default=5, ge=3, le=100)
    practical_speedup: float = Field(default=0.05, gt=0, le=1, allow_inf_nan=False)
    quality_abs_tolerance: float = Field(default=1e-6, ge=0, allow_inf_nan=False)
    quality_rel_tolerance: float = Field(default=0.01, ge=0, le=1, allow_inf_nan=False)
    max_rmse: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_model_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_python_rss_bytes: int | None = Field(default=None, gt=0)
    max_bench_memory_bytes: int | None = Field(default=None, gt=0)
    max_cpu_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class BenchmarkSpec(StrictSpec):
    kind: Literal["benchmark"] = "benchmark"
    dataset_version_id: UUID
    algorithm: Literal["linear_regression"] = "linear_regression"
    backends: tuple[Literal["madlib", "sklearn"], ...] = Field(
        default=("madlib", "sklearn"), min_length=1, max_length=2
    )
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    repeats: int = Field(default=5, ge=1, le=100)
    warmups: int = Field(default=1, ge=0, le=5)
    sample_sizes: tuple[int | None, ...] = (None,)
    fit_intercepts: tuple[bool, ...] = (True,)
    test_fraction: float = Field(default=0.2, gt=0, lt=1, allow_inf_nan=False)
    timeout_seconds: float = Field(default=300, gt=0, le=3600, allow_inf_nan=False)
    threads: int = Field(default=1, ge=1, le=16)
    recommendation: RecommendationPolicy = Field(default_factory=RecommendationPolicy)

    @model_validator(mode="after")
    def validate_matrix(self):
        if not self.sample_sizes or not self.fit_intercepts:
            raise ValueError("Matrix dimensions must not be empty")
        if any(n is not None and n < 4 for n in self.sample_sizes):
            raise ValueError("Sample size must be at least 4")
        if len(set(self.sample_sizes)) != len(self.sample_sizes):
            raise ValueError("Duplicate sample sizes")
        if len(set(self.fit_intercepts)) != len(self.fit_intercepts):
            raise ValueError("Duplicate intercept options")
        total = len(self.sample_sizes) * len(self.fit_intercepts) * len(self.backends)
        if total * (self.repeats + self.warmups) > 200:
            raise ValueError("Matrix exceeds 200 runs")
        return self

    @field_validator("backends")
    @classmethod
    def unique_backends(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Backends must be unique")
        return value


class DiagnosticSpec(StrictSpec):
    kind: Literal["diagnostic"] = "diagnostic"
    duration_seconds: float = Field(default=1, ge=0, le=300, allow_inf_nan=False)
    timeout_seconds: float = Field(default=30, gt=0, le=600, allow_inf_nan=False)
    mode: Literal["success", "fail", "hang"] = "success"


ExperimentSpec = Annotated[BenchmarkSpec | DiagnosticSpec, Field(discriminator="kind")]
spec_adapter = TypeAdapter(ExperimentSpec)


def spec_hash(spec: dict) -> str:
    body = json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest()


class DatasetSpec(StrictSpec):
    name: str = Field(min_length=1, max_length=128)
    source_schema: str = Field(default="public", min_length=1, max_length=63)
    source_table: str = Field(min_length=1, max_length=63)
    id_column: str = Field(min_length=1, max_length=63)
    features: tuple[str, ...] = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=63)

    @model_validator(mode="after")
    def distinct_columns(self):
        columns = (*self.features, self.target, self.id_column)
        if len(set(columns)) != len(columns) or any(not c or len(c) > 63 for c in columns):
            raise ValueError("Columns must be distinct, nonempty identifiers up to 63 characters")
        return self
