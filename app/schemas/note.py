"""Output 4 — Consultation note, rendered against a selected template.

Each section's content is derived from the grounded extraction; the aggregated
provenance lets a reviewer trace any line back to the source utterances.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.clinical import Provenance
from app.schemas.template import ComponentType


class NoteSection(BaseModel):
    section_id: str
    label: str
    component: ComponentType
    order: int = 0
    content_text: str = ""                         # human-readable rendering
    content_data: Any = None                       # structured payload (dict/list) for UI
    provenance: list[Provenance] = Field(default_factory=list)
    empty: bool = False                            # True when nothing was said for this section


class ConsultationNote(BaseModel):
    session_id: str
    template_id: str
    template_version: int
    sections: list[NoteSection] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_markdown(self) -> str:
        lines: list[str] = []
        for s in sorted(self.sections, key=lambda x: x.order):
            lines.append(f"## {s.label}")
            lines.append(s.content_text.strip() or "_Not discussed._")
            lines.append("")
        return "\n".join(lines).strip() + "\n"
