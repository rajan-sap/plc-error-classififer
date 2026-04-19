"""HTTP API smoke tests via FastAPI's in-process ``TestClient``.

Two tests: happy path (real fixture in, expected shape out) and input
validation (empty body rejected at the schema layer).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_classify_endpoint_returns_expected_classification(constant_error_log: str) -> None:
    r = client.post("/classify", json={"log_text": constant_error_log})

    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "mock"
    assert body["latency_ms"] < 3000   # the brief's SLA
    assert len(body["primary_root_ids"]) == 1

    primary = body["errors"][0]
    assert primary["severity"] == "blocking"
    assert primary["stage"] == "iec_compilation"
    assert primary["fix_complexity"] == "trivial"
    assert primary["parsed"]["category"] == "matiec.constant_assignment"
    assert len(primary["suggestions"]) >= 1


def test_classify_rejects_empty_log_with_422() -> None:
    # Pydantic's min_length=1 on log_text gives us free input validation.
    r = client.post("/classify", json={"log_text": ""})
    assert r.status_code == 422
