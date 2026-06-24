"""Shared fixtures: the brief's ENT example as a transcript + grounded extraction."""
from __future__ import annotations

import os

# ── Hermetic test config ──────────────────────────────────────────────────────
# The developer's local .env enables production wiring (SCRIBE_AUTH_MODE=jwt,
# SCRIBE_STORE_BACKEND=supabase). Tests must stay offline and use the dev header
# scaffold, so force a safe config here BEFORE app.* is imported. Process env vars
# take precedence over the .env file in pydantic-settings, so this overrides it.
os.environ["SCRIBE_AUTH_MODE"] = "dev"
os.environ["SCRIBE_STORE_BACKEND"] = "memory"
# Blank the JWT knobs so unit tests that construct Settings(auth_mode="jwt", ...) directly
# aren't tripped by the developer's .env (e.g. SCRIBE_JWT_AUDIENCE=authenticated would force
# every hand-rolled test token to carry an 'aud' claim). Explicit Settings(...) kwargs and
# os.environ both outrank the .env file in pydantic-settings.
for _k in ("SCRIBE_JWT_AUDIENCE", "SCRIBE_JWT_SECRET", "SCRIBE_JWT_JWKS_URL", "SCRIBE_JWT_ISSUER"):
    os.environ[_k] = ""

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()  # drop any settings cached from .env during collection

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_session_store():
    """Give each test a fresh in-memory session store (the get_store() singleton is
    module-global, so without this state leaks between tests)."""
    import app.store as _store_mod

    _store_mod._store = None
    yield
    _store_mod._store = None

from app.schemas.clinical import (
    ChiefComplaint,
    ClinicalExtraction,
    ExaminationFinding,
    Provenance,
)
from app.schemas.transcript import RawTranscript, SpeakerRole, TranscriptSegment
from app.templates.registry import TemplateRegistry


@pytest.fixture
def registry() -> TemplateRegistry:
    reg = TemplateRegistry()
    reg.load_dir()  # loads docs/templates/*.json
    return reg


@pytest.fixture
def ent_transcript() -> RawTranscript:
    rows = [
        (SpeakerRole.PATIENT, "I have throat pain for two months."),
        (SpeakerRole.PATIENT, "Yes, mostly with solid foods."),
        (SpeakerRole.PATIENT, "Yes, frequent discharge."),
        (SpeakerRole.DOCTOR, "Granular posterior pharyngeal wall, grade 2 tonsillar hypertrophy, DNS left."),
    ]
    segs = [
        TranscriptSegment(id=f"seg-{i + 1:04d}", speaker=spk, text=text, confidence=0.9)
        for i, (spk, text) in enumerate(rows)
    ]
    return RawTranscript(session_id="ent-demo", segments=segs)


@pytest.fixture
def ent_extraction() -> ClinicalExtraction:
    """Matches the brief's 'Expected Extraction', with provenance into ent_transcript."""
    return ClinicalExtraction(
        session_id="ent-demo",
        chief_complaints=[
            ChiefComplaint(symptom="Throat Pain", duration="2 Months",
                           provenance=Provenance(span_ids=["seg-0001"])),
            ChiefComplaint(symptom="Difficulty Swallowing", type="Solids > Liquids",
                           provenance=Provenance(span_ids=["seg-0002"])),
            ChiefComplaint(symptom="Frequent Nasal Discharge",
                           provenance=Provenance(span_ids=["seg-0003"])),
        ],
        examination=[
            ExaminationFinding(region="throat", finding="granular_ppw", value=True,
                               provenance=Provenance(span_ids=["seg-0004"])),
            ExaminationFinding(region="throat", finding="tonsillar_hypertrophy", value="Grade 2",
                               provenance=Provenance(span_ids=["seg-0004"])),
            ExaminationFinding(region="nose", finding="dns", value="Left",
                               provenance=Provenance(span_ids=["seg-0004"])),
        ],
    )


def section_by_id(note, section_id: str):
    return next(s for s in note.sections if s.section_id == section_id)
