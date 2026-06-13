"""Review/edit/sign-off flow: edit the generated note, then finalize with a signature."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.llm.base import DisabledLLM
from app.main import app

client = TestClient(app)

DOC = {"X-User-Id": "doc", "X-Role": "doctor"}


@pytest.fixture(autouse=True)
def _hermetic_llm(monkeypatch):
    # /simulate runs the pipeline via get_llm(); force the disabled provider so the
    # flow never touches a live LLM even when .env holds credentials.
    monkeypatch.setattr("app.pipeline.orchestrator.get_llm", lambda settings=None: DisabledLLM())


def _session_with_note() -> str:
    sid = client.post("/sessions", json={"template_id": "ent"}, headers=DOC).json()["session_id"]
    r = client.post(f"/sessions/{sid}/simulate", headers=DOC)
    assert r.status_code == 200, r.text
    return sid


def test_edit_note_saves_and_moves_to_edited():
    sid = _session_with_note()
    note = client.get(f"/sessions/{sid}/outputs/note", headers=DOC).json()
    target = note["sections"][0]["section_id"]

    r = client.post(
        f"/sessions/{sid}/note",
        json={"sections": [{"section_id": target, "content_text": "Doctor-edited content."}]},
        headers=DOC,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "edited"
    edited = next(s for s in r.json()["note"]["sections"] if s["section_id"] == target)
    assert edited["content_text"] == "Doctor-edited content."
    assert edited["empty"] is False


def test_edit_unknown_section_rejected():
    sid = _session_with_note()
    r = client.post(
        f"/sessions/{sid}/note",
        json={"sections": [{"section_id": "does-not-exist", "content_text": "x"}]},
        headers=DOC,
    )
    assert r.status_code == 422


def test_finalize_requires_signature_name():
    sid = _session_with_note()
    client.post(f"/sessions/{sid}/state", json={"state": "in_review"}, headers=DOC)
    client.post(f"/sessions/{sid}/state", json={"state": "approved"}, headers=DOC)
    r = client.post(f"/sessions/{sid}/state", json={"state": "finalized"}, headers=DOC)
    assert r.status_code == 422


def test_finalize_with_signature_then_export_carries_it():
    sid = _session_with_note()
    client.post(f"/sessions/{sid}/state", json={"state": "in_review"}, headers=DOC)
    client.post(f"/sessions/{sid}/state", json={"state": "approved"}, headers=DOC)
    r = client.post(
        f"/sessions/{sid}/state",
        json={"state": "finalized", "signed_by_name": "Dr. A. Rao"},
        headers=DOC,
    )
    assert r.status_code == 200, r.text

    record = client.get(f"/sessions/{sid}/export/json", headers=DOC).json()
    assert record["signature"]["signed_by_name"] == "Dr. A. Rao"

    md = client.get(f"/sessions/{sid}/export/markdown", headers=DOC).text
    assert "Dr. A. Rao" in md
