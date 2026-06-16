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


# ── Goal 3 per-consult Auto AI Mode toggle ───────────────────────────────────
_COMPLEX_TX = {
    "session_id": "x",
    "segments": [
        {"id": "seg-0001", "speaker": "doctor", "text": "What happened?", "confidence": 0.95, "start_ms": 0, "end_ms": 1500},
        {"id": "seg-0002", "speaker": "patient", "text": "My son has had fever for three days.", "confidence": 0.9, "start_ms": 1200, "end_ms": 3000},
        {"id": "seg-0003", "speaker": "other", "text": "And he is coughing a lot too.", "confidence": 0.55, "start_ms": 2800, "end_ms": 4500},
        {"id": "seg-0004", "speaker": "doctor", "text": "Is he vomiting?", "confidence": 0.95, "start_ms": 4300, "end_ms": 5200},
    ],
}


def test_mode_choice_drives_inference_mode():
    """Same complex consult, three pre-consult choices → three outcomes. Proves the
    Real-time / Batch / Auto selector is wired, not cosmetic (Goal 3)."""
    def run(mode: str) -> dict:
        sid = client.post("/sessions", json={"template_id": "soap", "mode": mode}, headers=DOC).json()["session_id"]
        return client.post(f"/sessions/{sid}/transcript", json=_COMPLEX_TX, headers=DOC).json()

    rt, ba, au, hy = run("realtime"), run("batch"), run("auto"), run("hybrid")
    assert rt["profile"]["is_complex"] is True   # the input really is complex
    assert rt["inference_mode"] == "realtime"    # manual real-time is honored even when complex
    assert ba["inference_mode"] == "batch"       # manual batch is honored
    assert au["inference_mode"] == "auto_batch"  # auto + complex → batch
    assert hy["inference_mode"] == "hybrid"      # hybrid is its own labeled mode


def test_legacy_auto_flag_still_works():
    """The older {auto: true} form keeps working as a fallback for `mode`."""
    sid = client.post("/sessions", json={"template_id": "soap", "auto": True}, headers=DOC).json()["session_id"]
    r = client.post(f"/sessions/{sid}/transcript", json=_COMPLEX_TX, headers=DOC).json()
    assert r["inference_mode"] == "auto_batch"


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


def test_ai_edit_undo_then_redo():
    sid = _session_with_transcript()
    note = client.get(f"/sessions/{sid}/outputs/note", headers=DOC).json()
    target = note["sections"][0]["section_id"]
    original = note["sections"][0]["content_text"]

    client.post(
        f"/sessions/{sid}/ai-edit/apply",
        json={"instruction": "x", "changes": [{"section_id": target, "content_text": "NEW TEXT"}]},
        headers=DOC,
    )

    undo = client.post(f"/sessions/{sid}/ai-edit/undo", headers=DOC)
    assert undo.status_code == 200, undo.text
    sec = next(s for s in undo.json()["note"]["sections"] if s["section_id"] == target)
    assert sec["content_text"] == original  # restored

    redo = client.post(f"/sessions/{sid}/ai-edit/redo", headers=DOC)
    assert redo.status_code == 200, redo.text
    sec = next(s for s in redo.json()["note"]["sections"] if s["section_id"] == target)
    assert sec["content_text"] == "NEW TEXT"  # re-applied

    # Nothing left to redo.
    assert client.post(f"/sessions/{sid}/ai-edit/redo", headers=DOC).status_code == 409


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
