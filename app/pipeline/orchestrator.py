"""Pipeline orchestration: raw transcript → clean → extract → ground → note → risk.

Used by both the WebSocket handler (at end-of-consult) and the REST process route.
Grounding runs *between* extraction and note generation so the note is built only
from grounded items.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.llm.base import MedicalLLM, get_llm
from app.pipeline.clean import clean_transcript
from app.pipeline.combined import analyze_consultation
from app.pipeline.complexity import assess_complexity
from app.pipeline.extract import extract_clinical
from app.pipeline.narrate import narrate_note
from app.pipeline.note import generate_note
from app.pipeline.risk import assess_risk, llm_risk_markers
from app.pipeline.subjects import resolve_relationships
from app.schemas.clinical import ClinicalExtraction
from app.schemas.intelligence import ConversationProfile
from app.schemas.note import ConsultationNote
from app.schemas.risk import RiskAssessment
from app.schemas.template import TemplateDefinition
from app.schemas.transcript import CleanTranscript, RawTranscript
from app.stt.doctor_detect import assign_clinical_roles
from app.validation.fidelity import verify_medication_fidelity
from app.validation.grounding import GroundingReport, ground_extraction


class PipelineResult(BaseModel):
    clean: CleanTranscript
    extraction: ClinicalExtraction
    grounding: GroundingReport
    note: ConsultationNote
    risk: RiskAssessment
    # Goal 1/2/4 — who is in the room, complexity, and confidence. None when subject
    # resolution is disabled. Never carries clinical content.
    profile: ConversationProfile | None = None


logger = logging.getLogger("svaani.pipeline")


def _staged_analyze(
    raw: RawTranscript, llm: MedicalLLM, settings: Settings
) -> tuple[CleanTranscript, ClinicalExtraction, list]:
    """Original three-call path: clean, then extract ∥ risk concurrently."""
    clean = clean_transcript(raw, llm, settings)
    # Extraction and the LLM risk pass both depend only on `clean`, so run them
    # concurrently — collapsing two sequential round-trips into one wall-clock wait.
    with ThreadPoolExecutor(max_workers=2) as pool:
        extraction_future = pool.submit(extract_clinical, clean, llm)
        risk_markers_future = pool.submit(llm_risk_markers, clean, llm)
        return clean, extraction_future.result(), risk_markers_future.result()


def _analyze(
    raw: RawTranscript, llm: MedicalLLM, settings: Settings
) -> tuple[CleanTranscript, ClinicalExtraction, list]:
    """Produce (clean, extraction, llm_risk_markers), preferring the single-pass call.

    With ``single_pass_llm`` the three LLM-derived artifacts come from ONE round-trip;
    any failure (or a disabled/absent LLM) falls back to the staged path so the note
    is never blocked.
    """
    if settings.single_pass_llm and llm.available:
        try:
            return analyze_consultation(raw, llm, settings)
        except Exception:  # noqa: BLE001 — best-effort; staged path is the safety net
            logger.warning("single-pass analysis failed; falling back to staged pipeline", exc_info=True)
    return _staged_analyze(raw, llm, settings)


def run_pipeline(
    raw: RawTranscript,
    template: TemplateDefinition,
    *,
    llm: MedicalLLM | None = None,
    settings: Settings | None = None,
) -> PipelineResult:
    settings = settings or get_settings()
    llm = llm or get_llm(settings)

    # Goal 1 (hardening): decide WHO the clinician is by behavior before anything downstream
    # inherits a wrong speaker-order label (e.g. the patient/caregiver spoke first). Cheap,
    # deterministic, no extra round-trip.
    if settings.resolve_subjects:
        assign_clinical_roles(raw)

    clean, extraction, risk_markers = _analyze(raw, llm, settings)

    # Goal 1: resolve WHO the consult is about before grounding the note, so symptoms
    # are attributed to the referenced patient (e.g. 'son') and not the speaker (mother).
    profile: ConversationProfile | None = None
    if settings.resolve_subjects:
        profile = resolve_relationships(clean if clean.segments else raw, llm)
        assess_complexity(profile, clean if clean.segments else raw, settings)
        # The LLM extraction may set referenced_patient itself; otherwise adopt the
        # resolver's answer so the note always knows whose record this is.
        if not extraction.referenced_patient and profile.referenced_patient:
            extraction.referenced_patient = profile.referenced_patient
        if not extraction.referenced_subjects and profile.referenced_subjects:
            extraction.referenced_subjects = [s.label for s in profile.referenced_subjects]

    valid_spans = raw.segment_ids() | clean.segment_ids()
    extraction, grounding = ground_extraction(
        extraction, valid_spans, drop=settings.drop_ungrounded_fields
    )

    # Fact verification: grounding only proves the cited span exists; this proves the
    # extracted medication name/dose was actually *said* in that span (catches a model
    # that normalized '1 mg' -> '40 mg' or renamed a drug). Non-destructive — it flags.
    grounding.verified, grounding.mismatched = verify_medication_fidelity(extraction, clean)

    note = generate_note(extraction, template)
    if settings.narrative_notes:
        # Faithful rephrasing of grounded section content into clinical prose. No-op
        # without an LLM; failure leaves the deterministic text untouched.
        note = narrate_note(note, llm)
    risk = assess_risk(clean, extraction, llm, settings, llm_markers=risk_markers)

    return PipelineResult(
        clean=clean, extraction=extraction, grounding=grounding, note=note, risk=risk,
        profile=profile,
    )


def rebuild_from_extraction(
    extraction: ClinicalExtraction,
    template: TemplateDefinition,
    clean: CleanTranscript | None,
    risk: RiskAssessment,
    settings: Settings,
    profile: ConversationProfile | None = None,
) -> PipelineResult:
    """Re-derive grounding + note from a DOCTOR-EDITED extraction (no LLM call).

    The doctor is the clinical authority, so we ground in *flag* mode — nothing is
    dropped; manually added items (which have no transcript provenance) are simply
    marked ungrounded for transparency. The note is re-rendered deterministically so
    edits are reflected instantly, and fact verification is re-run so the reviewer
    still sees which medication values match the transcript. Risk is left as-is (it is
    edited separately via its own endpoint).
    """
    valid_spans = clean.segment_ids() if clean else set()
    extraction, grounding = ground_extraction(extraction, valid_spans, drop=False)
    if clean is not None:
        grounding.verified, grounding.mismatched = verify_medication_fidelity(extraction, clean)
    note = generate_note(extraction, template)
    return PipelineResult(
        clean=clean or CleanTranscript(session_id=extraction.session_id),
        extraction=extraction, grounding=grounding, note=note, risk=risk, profile=profile,
    )
