"""API tests for the conversation-intelligence + ops layer (Goals 6-11 + prescription)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.data.repo as repo_mod
from app.llm.base import DisabledLLM
from app.main import app

client = TestClient(app)
DOC = {"X-User-Id": "doc", "X-Role": "doctor"}
ADMIN = {"X-User-Id": "adm", "X-Role": "admin"}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    # Force the disabled LLM so the pipeline is deterministic, and reset the in-memory
    # ops repo so review/admin/prompt state does not leak across tests.
    monkeypatch.setattr("app.pipeline.orchestrator.get_llm", lambda settings=None: DisabledLLM())
    repo_mod._repo = None
    yield
    repo_mod._repo = None


def _mother_son_transcript() -> dict:
    return {
        "session_id": "x",
        "segments": [
            {"id": "seg-0001", "speaker": "doctor", "text": "What happened?", "confidence": 0.97},
            {"id": "seg-0002", "speaker": "patient", "text": "My son has had fever for three days.", "confidence": 0.9},
            {"id": "seg-0003", "speaker": "doctor", "text": "Is he vomiting?", "confidence": 0.96},
            {"id": "seg-0004", "speaker": "patient", "text": "Yes, twice.", "confidence": 0.92},
        ],
    }


def _session_with_transcript() -> str:
    sid = client.post("/sessions", json={"template_id": "soap"}, headers=DOC).json()["session_id"]
    r = client.post(f"/sessions/{sid}/transcript", json=_mother_son_transcript(), headers=DOC)
    assert r.status_code == 200, r.text
    return sid


# ── Goal 1/2/4 profile ───────────────────────────────────────────────────────
def test_profile_resolves_referenced_patient():
    sid = _session_with_transcript()
    p = client.get(f"/sessions/{sid}/profile", headers=DOC).json()
    assert p["referenced_patient"] == "son"
    assert p["kind"] == "doctor_parent"
    assert any(s["role"] == "caregiver" for s in p["speakers"])


# ── Goal 6 speaker correction ─────────────────────────────────────────────────
def test_speaker_correction_updates_referenced_patient_and_renote():
    sid = _session_with_transcript()
    r = client.patch(
        f"/sessions/{sid}/speakers",
        json={"corrections": [{"speaker_label": "patient", "relationship": "guardian"}],
              "referenced_patient": "grandson"},
        headers=DOC,
    )
    assert r.status_code == 200, r.text
    assert r.json()["referenced_patient"] == "grandson"


# ── Goal 7/8/9 review -> admin -> improvement ─────────────────────────────────
def test_review_flow_enqueues_admin_and_seeds_improvement():
    sid = _session_with_transcript()
    rv = client.post(
        f"/sessions/{sid}/review",
        json={"rating": "needs_improvement", "error_categories": ["wrong_patient_identified"],
              "comment": "Patient should be the son."},
        headers=DOC,
    )
    assert rv.status_code == 200, rv.text

    # Doctor cannot see the admin console.
    assert client.get("/admin/reviews", headers=DOC).status_code == 403

    queue = client.get("/admin/reviews", headers=ADMIN).json()
    assert len(queue) == 1
    admin_id = queue[0]["admin_review"]["id"]

    upd = client.patch(f"/admin/reviews/{admin_id}", json={"status": "approved"}, headers=ADMIN)
    assert upd.status_code == 200, upd.text

    improvements = client.get("/admin/improvements", headers=ADMIN).json()
    assert len(improvements) == 1
    assert improvements[0]["stage"] == "issue_classification"

    item_id = improvements[0]["id"]
    adv = client.post(f"/admin/improvements/{item_id}/advance", json={}, headers=ADMIN)
    assert adv.json()["stage"] == "prompt_evaluation"


# ── Goal 10 prompt versioning ─────────────────────────────────────────────────
def test_prompt_versioning_activate():
    seeded = client.get("/prompts", headers=DOC).json()
    assert any(p["name"] == "extract" and p["active"] for p in seeded)

    # Doctor cannot create prompt versions.
    assert client.post("/prompts", json={"name": "extract", "content": "x"}, headers=DOC).status_code == 403

    created = client.post(
        "/prompts", json={"name": "extract", "content": "v2 content", "activate": True}, headers=ADMIN
    ).json()
    assert created["version"] == 2 and created["active"] is True

    after = client.get("/prompts?name=extract", headers=DOC).json()
    actives = [p for p in after if p["active"]]
    assert len(actives) == 1 and actives[0]["version"] == 2


# ── Goal 11 AI editor (unavailable without an LLM) ────────────────────────────
def test_ai_edit_requires_llm():
    sid = _session_with_transcript()
    r = client.post(f"/sessions/{sid}/ai-edit", json={"instruction": "be concise"}, headers=DOC)
    assert r.status_code == 503


def test_ai_edit_apply_records_history():
    sid = _session_with_transcript()
    note = client.get(f"/sessions/{sid}/outputs/note", headers=DOC).json()
    target = note["sections"][0]["section_id"]
    r = client.post(
        f"/sessions/{sid}/ai-edit/apply",
        json={"instruction": "tidy up", "changes": [{"section_id": target, "content_text": "Tidied."}]},
        headers=DOC,
    )
    assert r.status_code == 200, r.text
    edits = client.get(f"/sessions/{sid}/edits", headers=DOC).json()
    assert len(edits) == 1 and edits[0]["after"] == "Tidied."


# ── Prescription preview ──────────────────────────────────────────────────────
def test_prescription_preview_edit_approve():
    sid = _session_with_transcript()
    prev = client.post(
        f"/sessions/{sid}/document/preview",
        json={"doc_type": "prescription", "branding": {"name": "Test Hospital"}},
        headers=DOC,
    )
    assert prev.status_code == 200, prev.text
    doc = prev.json()
    assert doc["status"] == "previewed"
    assert "Test Hospital" in doc["rendered_html"]

    doc_id = doc["id"]
    ed = client.put(f"/documents/{doc_id}", json={"edited_html": "<div>edited rx</div>"}, headers=DOC)
    assert ed.json()["status"] == "edited"

    ap = client.post(f"/documents/{doc_id}/approve", headers=DOC)
    assert ap.json()["status"] == "approved"


# ── Goal 13 feature flags ─────────────────────────────────────────────────────
def test_feature_flags_read_and_admin_set():
    flags = client.get("/feature-flags", headers=DOC).json()
    assert "resolve_subjects" in flags["config"]
    assert client.post("/feature-flags", json={"key": "beta", "enabled": True}, headers=DOC).status_code == 403
    set_ok = client.post("/feature-flags", json={"key": "beta", "enabled": True}, headers=ADMIN)
    assert set_ok.json()["enabled"] is True
