"""Goal 1/2 hardening — golden multi-speaker attribution suite.

Drives each scripted, diarized consult through the REAL accuracy path (first-seen role
seeding → behavioral doctor detection → rule-based relationship resolution → complexity),
asserting the consult is attributed to the right patient(s). No LLM, fully deterministic.
This is the regression set the eval harness (Goal 9) reuses.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.eval.dataset import build_raw, load_dataset
from app.pipeline.complexity import assess_complexity
from app.pipeline.subjects import resolve_relationships
from app.schemas.transcript import SpeakerRole
from app.stt.doctor_detect import assign_clinical_roles

CASES = load_dataset("multispeaker@v1")


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_golden_attribution(case):
    exp = case.expect
    raw = build_raw(case)

    # 1) Behavioral doctor detection (the fix for first-seen mislabeling).
    assign_clinical_roles(raw)
    if "doctor_label" in exp:
        doctor_labels = {s.diarized_label for s in raw.segments if s.speaker is SpeakerRole.DOCTOR}
        assert doctor_labels == {exp["doctor_label"]}, (
            f"{case.id}: doctor should be {exp['doctor_label']}, got {doctor_labels}"
        )

    # 2) Relationship resolution (rule-based; LLM would only sharpen).
    profile = resolve_relationships(raw)
    assess_complexity(profile, raw, get_settings())

    if "referenced_patient" in exp:
        assert profile.referenced_patient == exp["referenced_patient"], case.id
    if "kind" in exp:
        assert profile.kind.value == exp["kind"], f"{case.id}: kind={profile.kind.value}"
    if "referenced_subjects" in exp:
        got = sorted(s.label for s in profile.referenced_subjects)
        assert got == sorted(exp["referenced_subjects"]), f"{case.id}: subjects={got}"
    if "has_roles" in exp:
        roles = {s.role.value for s in profile.speakers}
        for want in exp["has_roles"]:
            assert want in roles, f"{case.id}: expected role '{want}' in {roles}"
    if "is_complex" in exp:
        assert profile.is_complex is exp["is_complex"], (
            f"{case.id}: is_complex={profile.is_complex} score={profile.complexity_score}"
        )


def test_dataset_nonempty():
    assert len(CASES) >= 7  # the canonical hardening cases must all be present
