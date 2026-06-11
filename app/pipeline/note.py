"""Output 4 — consultation note. Deterministic, template-driven, LLM-free.

Rendering is pure formatting of the grounded extraction (see
``app.templates.renderer``), so the note can assert nothing the conversation didn't.
"""
from __future__ import annotations

from app.schemas.clinical import ClinicalExtraction
from app.schemas.note import ConsultationNote
from app.schemas.template import TemplateDefinition
from app.templates.renderer import render_note


def generate_note(extraction: ClinicalExtraction, template: TemplateDefinition) -> ConsultationNote:
    return render_note(extraction, template)
