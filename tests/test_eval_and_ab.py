"""Goal 9 eval harness + Goal 13 prompt A/B metrics."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.data.repo as repo_mod
from app.eval.runner import run_eval
from app.llm.base import DisabledLLM
from app.main import app

client = TestClient(app)
DOC = {"X-User-Id": "doc", "X-Role": "doctor"}
ADMIN = {"X-User-Id": "adm", "X-Role": "admin"}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.setattr("app.pipeline.orchestrator.get_llm", lambda settings=None: DisabledLLM())
    repo_mod._repo = None
    yield
    repo_mod._repo = None


def _session() -> str:
    sid = client.post("/sessions", json={"template_id": "soap"}, headers=DOC).json()["session_id"]
    client.post(f"/sessions/{sid}/transcript", json={
        "session_id": "x",
        "segments": [
            {"id": "seg-0001", "speaker": "doctor", "text": "What happened?", "confidence": 0.97},
            {"id": "seg-0002", "speaker": "patient", "text": "My son has had fever for three days.", "confidence": 0.9},
        ],
    }, headers=DOC)
    return sid


def test_run_eval_passes_golden_set():
    result = run_eval("multispeaker@v1")
    assert result["n_cases"] >= 7
    assert result["attribution"] == 1.0, result["failures"]
    assert result["passed"] is True and result["failures"] == []


def test_eval_endpoint_records_results():
    sid = _session()
    client.post(f"/sessions/{sid}/review", json={
        "rating": "needs_improvement", "error_categories": ["wrong_patient_identified"],
    }, headers=DOC)
    admin_id = client.get("/admin/reviews", headers=ADMIN).json()[0]["admin_review"]["id"]
    client.patch(f"/admin/reviews/{admin_id}", json={"status": "approved"}, headers=ADMIN)
    item_id = client.get("/admin/improvements", headers=ADMIN).json()[0]["id"]

    run = client.post(f"/admin/improvements/{item_id}/eval",
                      json={"dataset": "multispeaker@v1"}, headers=ADMIN)
    assert run.status_code == 200, run.text
    assert run.json()["passed"] is True

    got = client.get(f"/admin/improvements/{item_id}/eval", headers=ADMIN).json()
    assert got["attribution"] == 1.0

    # A doctor cannot run the eval, and an unknown dataset 404s.
    assert client.post(f"/admin/improvements/{item_id}/eval", json={}, headers=DOC).status_code == 403
    assert client.post(f"/admin/improvements/{item_id}/eval",
                       json={"dataset": "nope@v9"}, headers=ADMIN).status_code == 404


def test_ab_metrics_flow():
    cfg = client.post("/admin/prompts/relationship/ab",
                      json={"enabled": True, "b_pct": 100, "b_version_id": "pv-x"}, headers=ADMIN)
    assert cfg.status_code == 200, cfg.text

    sid = _session()
    assert client.post(f"/sessions/{sid}/review", json={"rating": "helpful"}, headers=DOC).status_code == 200

    metrics = client.get("/admin/prompts/relationship/ab/metrics", headers=ADMIN).json()
    assert metrics["arms"]["b"]["n"] == 1  # b_pct=100 routes everything to arm B
    assert metrics["arms"]["b"]["helpful"] == 1
    assert metrics["arms"]["b"]["needs_improvement_rate"] == 0.0

    # Auditor may read; doctor may not.
    assert client.get("/admin/prompts/relationship/ab/metrics", headers=DOC).status_code == 403


def test_analytics_endpoints():
    sid = _session()  # the transcript flow records a 'pipeline' latency row
    client.post(f"/sessions/{sid}/review", json={
        "rating": "needs_improvement", "error_categories": ["hallucination"],
    }, headers=DOC)

    errs = client.get("/admin/analytics/errors", headers=ADMIN).json()
    assert errs["total_reviews"] >= 1
    assert errs["by_error_category"].get("hallucination", 0) >= 1

    lat = client.get("/admin/analytics/latency", headers=ADMIN).json()
    assert lat["stages"].get("pipeline", {}).get("n", 0) >= 1

    assert client.get("/admin/analytics/errors", headers=DOC).status_code == 403
