"""Batch-mode benchmark — scorer unit tests + hermetic end-to-end plumbing.

The scorer math is asserted directly (deterministic, no LLM). The full runner is exercised
with ``mock=True`` (LLM-free) to prove the wiring — NOT the model's accuracy, which is a
manual live run via ``python -m app.eval.bench``.
"""
from __future__ import annotations

from app.eval.clinical_runner import run_clinical_eval
from app.eval.clinical_scorer import _number_present, score_case
from app.eval.dataset import GoldenCase
from app.schemas.clinical import ClinicalExtraction, ChiefComplaint, GroundedText, Provenance
from app.schemas.intelligence import ConversationProfile, SpeakerProfile
from app.schemas.transcript import SpeakerRole


def _p(spans: list[str]) -> Provenance:
    return Provenance(span_ids=spans)


def _full_extraction() -> ClinicalExtraction:
    """An extraction that captures the decision-critical cardiology facts correctly."""
    return ClinicalExtraction(
        session_id="t",
        chief_complaints=[ChiefComplaint(symptom="chest tightness", duration="2 months", provenance=_p(["seg-0002"]))],
        past_medical_history=[
            GroundedText(text="Diabetes for 8 years", provenance=_p(["seg-0007"])),
            GroundedText(text="Hypertension, on BP medications", provenance=_p(["seg-0007"])),
            GroundedText(text="Smoking: 1 pack/day, reduced last year", provenance=_p(["seg-0009"])),
        ],
        family_history=[GroundedText(text="Father had bypass surgery at 52", provenance=_p(["seg-0029"]))],
        investigations=[
            GroundedText(text="ECG: mild ST-segment depression", provenance=_p(["seg-0010"])),
            GroundedText(text="TMT positive", provenance=_p(["seg-0010"])),
            GroundedText(text="Ejection fraction 48%", provenance=_p(["seg-0019"])),
            GroundedText(text="LDL 168 mg/dL", provenance=_p(["seg-0032"])),
        ],
        assessment=GroundedText(text="Suspected myocardial ischemia; concerning for CAD", provenance=_p(["seg-0010"])),
        diagnosis=[GroundedText(text="Left ventricular hypertrophy", provenance=_p(["seg-0016"]))],
    )


def _golden() -> GoldenCase:
    return GoldenCase(
        id="unit",
        transcript=[{"speaker": "speaker_0", "text": "x"}],
        expect={
            "referenced_patient": "patient",
            "has_roles": ["doctor", "patient"],
            "facts": {
                "past_medical_history": [
                    {"name": "diabetes 8y", "aliases": ["diabetes"], "numbers": ["8"]},
                    {"name": "htn", "aliases": ["hypertension"]},
                ],
                "family_history": [{"name": "father bypass 52", "aliases": ["father", "bypass"], "numbers": ["52"]}],
                "investigations": [
                    {"name": "ef 48", "aliases": ["ejection fraction"], "numbers": ["48"]},
                    {"name": "tmt", "aliases": ["tmt"], "must": "positive"},
                ],
                "assessment_suspected": [{"name": "ischemia", "aliases": ["ischemia"]}],
                "diagnosis_confirmed": [{"name": "lvh", "aliases": ["left ventricular hypertrophy"]}],
            },
            "numbers_must_survive": ["8", "48", "168", "52"],
        },
    )


def _profile() -> ConversationProfile:
    return ConversationProfile(
        session_id="t",
        referenced_patient="patient",
        speakers=[
            SpeakerProfile(speaker_label="speaker_0", role=SpeakerRole.DOCTOR),
            SpeakerProfile(speaker_label="speaker_1", role=SpeakerRole.PATIENT),
        ],
    )


def test_number_token_boundary():
    # '8' must not match inside '48' or '168'.
    assert _number_present("8", "diabetes for 8 years")
    assert not _number_present("8", "ldl 168 mg/dl and ef 48%")
    assert _number_present("48", "ejection fraction 48%")
    assert not _number_present("48", "value 148")


def test_full_extraction_scores_high():
    res = score_case(_golden(), _full_extraction(), _profile())
    cats = res["categories"]
    assert cats["past_medical_history"]["recall"] == 1.0
    assert cats["family_history"]["recall"] == 1.0
    assert cats["investigations"]["recall"] == 1.0       # incl. TMT 'positive' qualifier
    assert res["numeric_fidelity"]["score"] == 1.0       # 8/48/168/52 all survive
    assert res["certainty"]["upgraded_to_confirmed"] == []
    assert res["attribution"]["score"] == 1.0
    assert res["overall"] > 0.9


def test_certainty_penalizes_suspected_as_confirmed():
    # Move the suspected ischemia into `diagnosis` → must be flagged as upgraded.
    ext = _full_extraction()
    ext.diagnosis.append(GroundedText(text="Myocardial ischemia", provenance=_p(["seg-0010"])))
    res = score_case(_golden(), ext, _profile())
    assert "ischemia" in " ".join(res["certainty"]["upgraded_to_confirmed"]).lower()
    assert res["certainty"]["score"] < 1.0


def test_missing_pmh_is_lost_not_misfiled():
    # Drop PMH entirely → diabetes is neither field-correct nor captured anywhere.
    ext = _full_extraction()
    ext.past_medical_history = []
    res = score_case(_golden(), ext, _profile())
    pmh = res["categories"]["past_medical_history"]
    assert pmh["recall"] == 0.0
    assert pmh["captured_anywhere"] == 0


def test_misfiled_pmh_is_captured_but_not_field_correct():
    # Diabetes captured only in HPI (wrong field) → lenient hit, strict miss.
    ext = _full_extraction()
    ext.past_medical_history = []
    ext.history_of_present_illness = GroundedText(text="Patient has diabetes for 8 years", provenance=_p(["seg-0007"]))
    res = score_case(_golden(), ext, _profile())
    pmh = res["categories"]["past_medical_history"]
    diabetes = next(i for i in pmh["items"] if "diabetes" in i["name"])
    assert diabetes["hit"] is False
    assert diabetes["captured_anywhere"] is True


def test_runner_mock_plumbing():
    out = run_clinical_eval("clinical@v1", template_id="general_medicine", mock=True)
    assert out["n_cases"] >= 1
    assert out["mock"] is True
    # Headline axes present.
    sc = out["scorecard"]
    for axis in ("Numeric Preservation", "Certainty", "Speaker Attribution"):
        assert axis in sc
    # Latency captured for the full pipeline.
    assert out["latency"]["total"]["n"] >= 1
    # Attribution works without an LLM (rule-based) — doctor/patient resolved.
    assert out["cases"][0]["attribution"]["score"] > 0.0
