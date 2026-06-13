"""Render a consultation note to PDF (reportlab — pure-Python, no system deps)."""
from __future__ import annotations

import base64
import binascii
import io
from datetime import datetime

from app.schemas.note import ConsultationNote


def _signature_flowables(
    signed_by_name: str | None,
    signed_at: datetime | None,
    signature_image: str | None,
    styles,
):
    """Build the sign-off block: optional drawn/uploaded image + name + timestamp."""
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Image, Paragraph, Spacer

    flow = [Spacer(1, 8 * mm), HRFlowable(width="100%"), Spacer(1, 3 * mm)]
    flow.append(Paragraph("Electronically signed", styles["Heading3"]))

    if signature_image and "," in signature_image:
        try:
            raw = base64.b64decode(signature_image.split(",", 1)[1], validate=False)
            img = Image(io.BytesIO(raw))
            # Scale to a sensible signature size (max ~70mm wide), preserving ratio.
            max_w = 70 * mm
            if img.imageWidth and img.drawWidth > max_w:
                ratio = max_w / float(img.imageWidth)
                img.drawWidth = max_w
                img.drawHeight = img.imageHeight * ratio
            flow.append(img)
            flow.append(Spacer(1, 2 * mm))
        except (binascii.Error, ValueError, OSError):
            pass  # never let a malformed signature image block the export

    when = signed_at.strftime("%Y-%m-%d %H:%M UTC") if signed_at else ""
    flow.append(Paragraph(f"<b>{signed_by_name}</b>", styles["Normal"]))
    if when:
        flow.append(Paragraph(when, styles["Normal"]))
    return flow


def note_to_pdf(
    note: ConsultationNote,
    *,
    title: str = "Consultation Note",
    signed_by_name: str | None = None,
    signed_at: datetime | None = None,
    signature_image: str | None = None,
) -> bytes:
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

    if signed_by_name:
        flow.extend(_signature_flowables(signed_by_name, signed_at, signature_image, styles))

    doc.build(flow)
    return buf.getvalue()
