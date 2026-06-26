"""POST /templates — the save path behind the drag-and-drop builder.

Templates are written to a tmp dir (monkeypatched) so tests never pollute the
repo's seed templates under docs/templates/.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ADMIN = {"X-User-Id": "tester", "X-Role": "admin"}


def _template(template_id: str, sections: list[dict]) -> dict:
    return {"template_id": template_id, "name": template_id.upper(), "sections": sections}


def test_create_template_appears_in_list():
    body = _template("builttpl", [
        {"id": "cc", "component": "CHIEF_COMPLAINTS", "label": "Chief Complaints", "order": 1},
        {"id": "dx", "component": "DIAGNOSIS", "label": "Diagnosis", "order": 2},
    ])
    r = client.post("/templates", json=body, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json() == {"template_id": "builttpl", "version": 1}

    listed = {t["template_id"] for t in client.get("/templates").json()}
    assert "builttpl" in listed


def test_custom_section_without_hint_rejected():
    body = _template("badtpl", [
        {"id": "x", "component": "CUSTOM", "label": "X", "order": 1},  # missing schema_hint
    ])
    r = client.post("/templates", json=body, headers=ADMIN)
    assert r.status_code == 422


def test_duplicate_section_ids_rejected():
    body = _template("duptpl", [
        {"id": "same", "component": "CHIEF_COMPLAINTS", "label": "A", "order": 1},
        {"id": "same", "component": "DIAGNOSIS", "label": "B", "order": 2},
    ])
    r = client.post("/templates", json=body, headers=ADMIN)
    assert r.status_code == 422


def test_existing_template_id_bumps_version():
    sections = [{"id": "cc", "component": "CHIEF_COMPLAINTS", "label": "CC", "order": 1}]
    first = client.post("/templates", json=_template("verbump", sections), headers=ADMIN)
    assert first.json()["version"] == 1
    second = client.post("/templates", json=_template("verbump", sections), headers=ADMIN)
    assert second.json()["version"] == 2


def test_doctor_can_manage_templates():
    # Clinicians author their own templates without switching to admin.
    sections = [{"id": "cc", "component": "CHIEF_COMPLAINTS", "label": "CC", "order": 1}]
    r = client.post("/templates", json=_template("doctpl", sections),
                    headers={"X-User-Id": "doc", "X-Role": "doctor"})
    assert r.status_code == 200, r.text


def test_role_without_manage_templates_forbidden():
    # A role that genuinely lacks MANAGE_TEMPLATES (scribe) is still rejected.
    sections = [{"id": "cc", "component": "CHIEF_COMPLAINTS", "label": "CC", "order": 1}]
    r = client.post("/templates", json=_template("nope", sections),
                    headers={"X-User-Id": "scr", "X-Role": "scribe"})
    assert r.status_code == 403
