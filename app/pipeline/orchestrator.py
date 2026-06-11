"""Pipeline orchestration: raw transcript → clean → extract → ground → note → risk.

Used by both the WebSocket handler (at end-of-consult) and the REST process route.
Grounding runs *between* extraction and note generation so the note is built only
from grounded items.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.llm.base import MedicalLLM, get_llm
from app.pipeline.clean import clean_transcript
from app.pipeline.extract import extract_clinical
from app.pipeline.note import generate_note
from app.pipeline.risk import assess_risk
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
    extraction = extract_clinical(clean, llm)

    valid_spans = raw.segment_ids() | clean.segment_ids()
    extraction, grounding = ground_extraction(
        extraction, valid_spans, drop=settings.drop_ungrounded_fields
    )

    note = generate_note(extraction, template)
    risk = assess_risk(clean, extraction, llm, settings)

    return PipelineResult(
        clean=clean, extraction=extraction, grounding=grounding, note=note, risk=risk
    )
