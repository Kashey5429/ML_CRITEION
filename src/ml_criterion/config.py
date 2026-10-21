from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ML_", env_file=".env", extra="ignore")
    metadata_url: str = "postgresql+psycopg://criterion:local-metadata@localhost:55432/criterion"
    bench_dsn: str = "postgresql://bench:local-bench@localhost:55433/bench"
    poll_seconds: float = Field(default=1, gt=0)
    heartbeat_seconds: float = Field(default=5, gt=0)
    lease_seconds: int = Field(default=30, ge=3)
    enable_diagnostic_jobs: bool = False
    source_schemas: tuple[str, ...] = ("public",)
    max_dataset_rows: int = Field(default=1000000, ge=4)
    sklearn_memory_mb: int = Field(default=512, ge=16)
    artifact_root: str = "/artifacts"
    resource_sample_seconds: float = Field(default=0.1, ge=0.05, le=2, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_lease(self):
        if self.heartbeat_seconds * 3 > self.lease_seconds:
            raise ValueError("lease_seconds must be at least three heartbeat intervals")
        return self
