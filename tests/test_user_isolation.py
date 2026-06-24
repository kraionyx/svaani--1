"""Per-user data isolation: GET /sessions returns only the caller's own consultations,
and a created session is owned by the authenticated caller (practitioner_id)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _h(uid: str) -> dict:
    return {"X-User-Id": uid, "X-Role": "doctor"}


def test_sessions_listed_per_user():
    a = client.post("/sessions", json={"template_id": "soap"}, headers=_h("alice")).json()["session_id"]
    b = client.post("/sessions", json={"template_id": "soap"}, headers=_h("bob")).json()["session_id"]

    r = client.get("/sessions", headers=_h("alice"))
    assert r.status_code == 200, r.text
    alice_ids = [row["session_id"] for row in r.json()]
    assert a in alice_ids and b not in alice_ids

    bob_ids = [row["session_id"] for row in client.get("/sessions", headers=_h("bob")).json()]
    assert b in bob_ids and a not in bob_ids


def test_created_session_owned_by_caller():
    sid = client.post("/sessions", json={"template_id": "soap"}, headers=_h("carol")).json()["session_id"]
    rows = client.get("/sessions", headers=_h("carol")).json()
    row = next(r for r in rows if r["session_id"] == sid)
    assert row["practitioner_id"] == "carol"


def test_request_cannot_assign_session_to_another_user():
    # A client-supplied practitioner_id is ignored — ownership is always the caller.
    sid = client.post(
        "/sessions", json={"template_id": "soap", "practitioner_id": "victim"}, headers=_h("attacker")
    ).json()["session_id"]
    assert sid not in [r["session_id"] for r in client.get("/sessions", headers=_h("victim")).json()]
    assert sid in [r["session_id"] for r in client.get("/sessions", headers=_h("attacker")).json()]
