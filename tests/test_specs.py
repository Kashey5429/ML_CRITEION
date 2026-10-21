import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ml_criterion.api.app import create_app
from ml_criterion.config import Settings
from ml_criterion.domain.specs import DiagnosticSpec, spec_hash


def test_hash_ignores_object_key_order():
    assert spec_hash({"a": 1, "b": 2}) == spec_hash({"b": 2, "a": 1})


@pytest.mark.parametrize("value", [-1, 301, float("inf"), float("nan")])
def test_invalid_duration(value):
    with pytest.raises(ValidationError):
        DiagnosticSpec(duration_seconds=value)


def test_spec_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        DiagnosticSpec(sql="DROP DATABASE")


def test_lease_must_cover_heartbeats():
    with pytest.raises(ValidationError):
        Settings(lease_seconds=3, heartbeat_seconds=2)


def test_liveness_and_capabilities_do_not_require_database():
    with TestClient(create_app(Settings(), sessions=object())) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/api/v1/capabilities").json()["benchmark_execution"] is True
        assert client.post("/api/v1/experiments", json={"kind": "unknown"}).status_code == 422
