"""Template renderer — maps a grounded ``ClinicalExtraction`` onto a template.

Pure, deterministic, LLM-free: it only *organizes and formats* what the extraction
already contains, so the rendered note can assert nothing the conversation didn't.
``CUSTOM`` sections resolve a dotted ``schema_hint`` (e.g. ``examination.nose``)
against the extraction's data map.
"""
from __future__ import annotations

from typing import Any

from app.schemas.clinical import ClinicalExtraction, Provenance
from app.schemas.note import ConsultationNote, NoteSection
from app.schemas.template import (
    COMPONENT_DEFAULT_SOURCE,
    ComponentType,
    TemplateDefinition,
    TemplateSection,
)


def _resolve_path(data: dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _is_empty(value: Any) -> bool:
    return value is None or value == [] or value == {} or value == ""


def _humanize_finding(finding: str, value: Any) -> str:
    """Render one examination finding as readable text, avoiding 'clear: clear'.

    Deterministic fallback only — when an LLM is configured the note is re-narrated
    into prose (see ``app.pipeline.narrate``). Examples:
      ('granular_ppw', True)            -> 'granular ppw'
      ('rashes', 'no rashes')           -> 'no rashes'
      ('tonsillar_hypertrophy', 'Grade 2') -> 'tonsillar hypertrophy (Grade 2)'
      ('clear', 'clear')                -> 'clear'
    """
    label = finding.replace("_", " ").strip()
    if value is True:
        return label
    if value is False:
        return f"no {label}"
    sval = str(value).strip()
    if not sval:
        return label
    if sval.lower() == label.lower() or label.lower() in sval.lower():
        return sval
    return f"{label} ({sval})"


def _format_value(component: ComponentType, value: Any) -> str:
    if _is_empty(value):
        return ""
    if component is ComponentType.CHIEF_COMPLAINTS and isinstance(value, list):
        lines = []
        for c in value:
            extra = ", ".join(str(c[k]) for k in ("duration", "type") if c.get(k))
            lines.append(f"- {c.get('symptom', '')}" + (f" ({extra})" if extra else ""))
        return "\n".join(lines)
    if component is ComponentType.ALLERGIES and isinstance(value, list):
        return "\n".join(
            f"- {a.get('substance', '')}" + (f" — {a['reaction']}" if a.get("reaction") else "")
            for a in value
        )
    if component in {ComponentType.PATIENT_INFORMATION, ComponentType.VITALS} and isinstance(value, dict):
        return "\n".join(f"- {k}: {v}" for k, v in value.items())
    if component is ComponentType.EXAMINATION and isinstance(value, dict):
        out = []
        for region, findings in value.items():
            if isinstance(findings, dict):
                items = [_humanize_finding(k, v) for k, v in findings.items()]
                out.append(f"- {region.title()}: " + ", ".join(items) + ".")
            else:
                out.append(f"- {region.title()}: {findings}.")
        return "\n".join(out)
    if isinstance(value, list):
        return "\n".join(f"- {v}" for v in value)
    if isinstance(value, dict):
        return "\n".join(f"- {k}: {v}" for k, v in value.items())
    return str(value)


def _section_provenance(extraction: ClinicalExtraction, section: TemplateSection) -> list[Provenance]:
    """Best-effort gather of provenance for the items feeding this section."""
    c = section.component
    if c is ComponentType.CHIEF_COMPLAINTS:
        return [x.provenance for x in extraction.chief_complaints]
    if c is ComponentType.ALLERGIES:
        return [x.provenance for x in extraction.allergies]
    if c is ComponentType.EXAMINATION:
        return [f.provenance for f in extraction.examination]
    if c is ComponentType.DIAGNOSIS:
        return [g.provenance for g in extraction.diagnosis]
    if c is ComponentType.TREATMENT_PLAN:
        return [g.provenance for g in extraction.treatment_plan]
    if c is ComponentType.INVESTIGATIONS:
        return [g.provenance for g in extraction.investigations]
    if c is ComponentType.PAST_MEDICAL_HISTORY:
        return [g.provenance for g in extraction.past_medical_history]
    if c is ComponentType.FAMILY_HISTORY:
        return [g.provenance for g in extraction.family_history]
    if c is ComponentType.HISTORY_OF_PRESENT_ILLNESS and extraction.history_of_present_illness:
        return [extraction.history_of_present_illness.provenance]
    if c is ComponentType.ASSESSMENT and extraction.assessment:
        return [extraction.assessment.provenance]
    if c is ComponentType.FOLLOW_UP and extraction.follow_up:
        return [extraction.follow_up.provenance]
    if c is ComponentType.DOCTOR_NOTES and extraction.doctor_notes:
        return [extraction.doctor_notes.provenance]
    if c is ComponentType.CUSTOM and section.schema_hint:
        # e.g. "examination.throat" -> provenance of throat findings
        parts = section.schema_hint.split(".")
        if parts[0] == "examination" and len(parts) == 2:
            return [f.provenance for f in extraction.examination if f.region == parts[1]]
    return []


def render_note(extraction: ClinicalExtraction, template: TemplateDefinition) -> ConsultationNote:
    data = extraction.to_data_map()
    sections: list[NoteSection] = []

    for sec in template.active_sections():
        if sec.component is ComponentType.CUSTOM:
            source = sec.schema_hint or ""
            value = _resolve_path(data, source)
            # render custom examination sub-paths with the examination formatter
            fmt_component = (
                ComponentType.EXAMINATION
                if source.startswith("examination.") and isinstance(value, dict)
                else sec.component
            )
            content_text = (
                _format_value(ComponentType.EXAMINATION, {source.split(".")[-1]: value})
                if fmt_component is ComponentType.EXAMINATION
                else _format_value(sec.component, value)
            )
        else:
            source = sec.schema_hint or COMPONENT_DEFAULT_SOURCE[sec.component]
            value = _resolve_path(data, source)
            content_text = _format_value(sec.component, value)

        sections.append(
            NoteSection(
                section_id=sec.id,
                label=sec.label,
                component=sec.component,
                order=sec.order,
                content_text=content_text,
                content_data=value,
                provenance=_section_provenance(extraction, sec),
                empty=_is_empty(value),
            )
        )

    return ConsultationNote(
        session_id=extraction.session_id,
        template_id=template.template_id,
        template_version=template.version,
        sections=sections,
    )
