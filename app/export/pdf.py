"""Render a consultation note to PDF (reportlab — pure-Python, no system deps)."""
from __future__ import annotations

import io

from app.schemas.note import ConsultationNote


def note_to_pdf(note: ConsultationNote, *, title: str = "Consultation Note") -> bytes:
    from reportlab.lib.pagesizes import A4  # deferred
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    flow = [
        Paragraph(title, styles["Title"]),
        Paragraph(
            f"Session {note.session_id} · template {note.template_id}@{note.template_version} · "
            f"generated {note.generated_at:%Y-%m-%d %H:%M UTC}",
            styles["Normal"],
        ),
        Spacer(1, 8 * mm),
    ]
    for section in sorted(note.sections, key=lambda s: s.order):
        flow.append(Paragraph(section.label, styles["Heading2"]))
        body = (section.content_text or "Not discussed.").replace("\n", "<br/>")
        flow.append(Paragraph(body, styles["Normal"]))
        flow.append(Spacer(1, 4 * mm))

    doc.build(flow)
    return buf.getvalue()
