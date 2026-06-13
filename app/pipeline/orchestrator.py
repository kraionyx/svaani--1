"""Pipeline orchestration: raw transcript → clean → extract → ground → note → risk.

Used by both the WebSocket handler (at end-of-consult) and the REST process route.
Grounding runs *between* extraction and note generation so the note is built only
from grounded items.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.llm.base import MedicalLLM, get_llm
from app.pipeline.clean import clean_transcript
from app.pipeline.extract import extract_clinical
from app.pipeline.narrate import narrate_note
from app.pipeline.note import generate_note
from app.pipeline.risk import assess_risk, llm_risk_markers
from app.schemas.clinical import ClinicalExtraction
from app.schemas.note import ConsultationNote
from app.schemas.risk import RiskAssessment
from app.schemas.template import TemplateDefinition
from app.schemas.transcript import CleanTranscript, RawTranscript
from app.validation.grounding import GroundingReport, ground_extraction


class PipelineResult(BaseModel):
    clean: CleanTranscript
    extraction: ClinicalExtraction
    grounding: GroundingReport
    note: ConsultationNote
    risk: RiskAssessment


def run_pipeline(
    raw: RawTranscript,
    template: TemplateDefinition,
    *,
    llm: MedicalLLM | None = None,
    settings: Settings | None = None,
) -> PipelineResult:
    settings = settings or get_settings()
    llm = llm or get_llm(settings)

    clean = clean_transcript(raw, llm, settings)

    # Extraction and the LLM risk pass both depend only on `clean`, so run them
    # concurrently — this collapses two sequential round-trips into one wall-clock
    # wait. Rule-based risk + grounding still run after, on the grounded extraction.
    with ThreadPoolExecutor(max_workers=2) as pool:
        extraction_future = pool.submit(extract_clinical, clean, llm)
        risk_markers_future = pool.submit(llm_risk_markers, clean, llm)
        extraction = extraction_future.result()
        risk_markers = risk_markers_future.result()

    valid_spans = raw.segment_ids() | clean.segment_ids()
    extraction, grounding = ground_extraction(
        extraction, valid_spans, drop=settings.drop_ungrounded_fields
    )

    note = generate_note(extraction, template)
    if settings.narrative_notes:
        # Faithful rephrasing of grounded section content into clinical prose. No-op
        # without an LLM; failure leaves the deterministic text untouched.
        note = narrate_note(note, llm)
    risk = assess_risk(clean, extraction, llm, settings, llm_markers=risk_markers)

    return PipelineResult(
        clean=clean, extraction=extraction, grounding=grounding, note=note, risk=risk
    )
