"""Prescription / hospital-document renderer (deterministic, LLM-free).

The hospital supplies its own printable design as HTML/CSS with ``{{placeholder}}``
tokens (see ``DocumentTemplate``). This module fills those tokens with DOCTOR-CONFIRMED
content drawn from the finalized note/extraction plus hospital branding — it never
authors a prescription or adds clinical content. The doctor previews, edits, and
explicitly approves the result.

Substitution is a plain ``{{key}}`` replace with HTML-escaped values, so transcript
content can never inject markup. Unknown placeholders render empty.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

from app.schemas.document import DocumentTemplate
from app.schemas.session import ConsultationSession

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

# Defense-in-depth for the one place raw HTML is trusted: the hospital DocumentTemplate body
# and doctor-edited document HTML. Placeholder VALUES are already HTML-escaped, but the
# template/edit author's markup is rendered as-is — a prescription never needs scripting, so
# we strip active content. Regex sanitization isn't a full HTML parser, but for this narrow,
# privileged, script-free document surface it removes the realistic XSS vectors.
_SCRIPT_RE = re.compile(r"<\s*(script|iframe|object|embed|link|meta|base)\b[^>]*>.*?<\s*/\s*\1\s*>",
                        re.IGNORECASE | re.DOTALL)
_VOID_TAG_RE = re.compile(r"<\s*(script|iframe|object|embed|link|meta|base)\b[^>]*/?>",
                          re.IGNORECASE)
_ON_ATTR_RE = re.compile(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_JS_URI_RE = re.compile(r"(href|src|xlink:href)\s*=\s*(\"|')?\s*javascript:[^\"'>\s]*",
                        re.IGNORECASE)


def sanitize_html(raw: str | None) -> str:
    """Strip active content (scripts, frames, event handlers, javascript: URLs) from
    trusted-but-author-supplied document HTML. Layout/markup is preserved."""
    if not raw:
        return ""
    cleaned = _SCRIPT_RE.sub("", raw)
    cleaned = _VOID_TAG_RE.sub("", cleaned)
    cleaned = _ON_ATTR_RE.sub("", cleaned)
    cleaned = _JS_URI_RE.sub(lambda m: f"{m.group(1)}=", cleaned)
    return cleaned


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _join_grounded(items: list) -> str:
    """Render a list of GroundedText / strings as an HTML <ul>."""
    texts = []
    for it in items:
        t = getattr(it, "text", None)
        texts.append(t if t is not None else str(it))
    texts = [t for t in texts if (t or "").strip()]
    if not texts:
        return ""
    return "<ul>" + "".join(f"<li>{_esc(t)}</li>" for t in texts) + "</ul>"


def _medications_html(extraction) -> str:
    """Medications DISCUSSED (verbatim, non-authoritative). The doctor edits/confirms."""
    meds = getattr(extraction, "medications_discussed", []) or []
    if not meds:
        return ""
    rows = []
    for m in meds:
        parts = [m.name]
        for f in (m.dose, m.frequency, m.duration, m.route):
            if f:
                parts.append(f)
        rows.append(f"<li>{_esc(' — '.join(parts))}</li>")
    return "<ul>" + "".join(rows) + "</ul>"


def _examination_html(extraction) -> str:
    """Physical-examination findings + objective vitals, as an HTML list. Empty when the
    consult recorded no exam (faithful: a blank box can be hand-completed on the print-out)."""
    rows: list[str] = []
    for f in (getattr(extraction, "examination", []) or []):
        region = str(getattr(f, "region", "")).replace("_", " ").strip()
        finding = str(getattr(f, "finding", "")).replace("_", " ").strip()
        value = getattr(f, "value", None)
        label = " — ".join(p for p in (f"{region}: {finding}".strip(": "), str(value) if value not in (None, "") else "") if p)
        if label.strip():
            rows.append(f"<li>{_esc(label)}</li>")
    for k, v in (getattr(extraction, "vitals", {}) or {}).items():
        rows.append(f"<li>{_esc(f'{k}: {v}')}</li>")
    return "<ul>" + "".join(rows) + "</ul>" if rows else ""


def build_context(session: ConsultationSession, branding: dict | None = None) -> dict[str, str]:
    """Assemble the placeholder context from doctor-confirmed session content."""
    branding = branding or {}
    ex = session.extraction
    pinfo = (ex.patient_information if ex else {}) or {}
    now = datetime.now(timezone.utc)

    age = pinfo.get("age", "")
    sex = pinfo.get("sex", pinfo.get("gender", ""))
    age_sex = " / ".join(p for p in (str(age).strip(), str(sex).strip()) if p)

    ctx: dict[str, str] = {
        # Hospital branding (from the hospital record / DocumentTemplate owner). The
        # default prescription template is the seeded Continental "OP Note" design, so
        # the header falls back to those values when the caller passes no branding.
        "hospital_name": _esc(branding.get("name") or "CONTINENTAL HOSPITALS"),
        "department": _esc(branding.get("department") or "ORTHOPAEDICS, JOINT CENTRE & SPORTS CLINIC"),
        "hospital_address": _esc(branding.get("address", "")),
        "hospital_logo_url": _esc(branding.get("logo_url", "")),
        "registration_no": _esc(branding.get("registration_no", "")),
        "footer": _esc(branding.get("footer", "")),
        # Doctor / patient block.
        "doctor_name": _esc(session.signed_by_name or branding.get("doctor_name", "")),
        "doctor_reg": _esc(branding.get("doctor_reg", "")),
        "patient_name": _esc(pinfo.get("name", "")),
        "patient_age": _esc(age),
        "patient_sex": _esc(sex),
        "patient_age_sex": _esc(age_sex),
        "patient_id": _esc(session.patient_id or pinfo.get("id", "")),
        "encounter_id": _esc(session.session_id),
        "visit_type": _esc(branding.get("visit_type") or "Outpatient (OP)"),
        "referenced_patient": _esc(ex.referenced_patient if ex else ""),
        "date": _esc(now.strftime("%d %b %Y")),
        "rx_symbol": "&#8478;",  # ℞
        # Filled only when the consult captured them; otherwise the print-out shows a
        # blank box/line to complete by hand (faithful — the AI authors nothing).
        "physical_examination": _examination_html(ex) if ex is not None else "",
        "recommended_investigation": _join_grounded(ex.investigations) if ex is not None else "",
    }

    if ex is not None:
        ctx["diagnosis"] = _join_grounded(ex.diagnosis)
        ctx["medications"] = _medications_html(ex)
        ctx["treatment_plan"] = _join_grounded(ex.treatment_plan)
        ctx["advice"] = _join_grounded(ex.treatment_plan)
        ctx["follow_up"] = _esc(ex.follow_up.text if ex.follow_up else "")
        ctx["chief_complaints"] = _join_grounded(
            [c.symptom for c in ex.chief_complaints]
        )
        ctx["vitals"] = "<br/>".join(f"{_esc(k)}: {_esc(v)}" for k, v in (ex.vitals or {}).items())
    # Signature block.
    if session.signature_image:
        ctx["signature"] = f'<img src="{_esc(session.signature_image)}" alt="signature" style="max-height:60px"/>'
    else:
        ctx["signature"] = _esc(session.signed_by_name or "")
    return ctx


def render_document(template: DocumentTemplate, context: dict[str, str]) -> str:
    """Substitute ``{{key}}`` tokens in the template HTML; wrap with its CSS.

    The author-supplied template body is sanitized (scripts/handlers/js: URLs removed) as
    defense-in-depth; placeholder values were already HTML-escaped during context build."""
    body = _TOKEN_RE.sub(lambda m: context.get(m.group(1), ""), template.html)
    body = sanitize_html(body)
    style = f"<style>{template.css}</style>" if template.css else ""
    return f"{style}\n{body}"


def render_for_session(
    template: DocumentTemplate, session: ConsultationSession, branding: dict | None = None
) -> str:
    return render_document(template, build_context(session, branding))


# ── Default hospital prescription template — Continental "OP Note" ──────────────
# The hospital's printable OP-note design. Patient-block lines and the two clinical
# boxes are {{placeholders}} filled from DOCTOR-CONFIRMED content; a missing value
# leaves the ruled line / box blank so it can be completed by hand on the print-out.
_DEFAULT_HTML = """
<div class="container">
  <div class="header">
    <div class="hospital-name">{{hospital_name}}</div>
    <div class="department">{{department}}</div>
  </div>

  <div class="title">OP NOTE</div>

  <div class="patient-info">
    <div class="field">Patient ID : <span class="line">{{patient_id}}</span></div>
    <div class="field">Encounter ID : <span class="line">{{encounter_id}}</span></div>
    <div class="field">Patient Name : <span class="line">{{patient_name}}</span></div>
    <div class="field">Age / Gender : <span class="line">{{patient_age_sex}}</span></div>
    <div class="field">Consultant : <span class="line">{{doctor_name}}</span></div>
    <div class="field">Date of Visit : <span class="line">{{date}}</span></div>
    <div class="field">Visit Type : <span class="line">{{visit_type}}</span></div>
  </div>

  <div class="section">
    <div class="section-title">PHYSICAL EXAMINATION</div>
    <div class="section-box">{{physical_examination}}</div>
  </div>

  <div class="section">
    <div class="section-title">RECOMMENDED INVESTIGATION</div>
    <div class="section-box">{{recommended_investigation}}</div>
  </div>

  <div class="signature">
    <div class="signature-line">{{signature}}</div><br>
    Doctor Signature
  </div>
</div>
"""

_DEFAULT_CSS = (
    "*{margin:0;padding:0;box-sizing:border-box;font-family:Arial,Helvetica,sans-serif}"
    "body{background:#fff;padding:30px}"
    ".container{max-width:900px;margin:auto}"
    ".header{text-align:center;margin-bottom:25px}"
    ".hospital-name{font-size:24px;font-weight:700;letter-spacing:1px}"
    ".department{font-size:16px;font-weight:600;margin-top:5px}"
    ".title{text-align:center;font-size:20px;font-weight:bold;margin:25px 0;text-decoration:underline}"
    ".patient-info{display:grid;grid-template-columns:1fr 1fr;gap:12px 40px;margin-bottom:25px}"
    ".field{font-size:14px}"
    ".line{display:inline-block;min-width:220px;border-bottom:1px solid #000;min-height:18px;"
    "line-height:18px;vertical-align:bottom;font-weight:600}"
    ".section{margin-top:20px}"
    ".section-title{font-weight:bold;font-size:15px;margin-bottom:8px}"
    ".section-box{border:1px solid #000;min-height:180px;padding:10px;font-size:14px;line-height:1.6}"
    ".section-box ul{margin:0;padding-left:20px}.section-box li{margin:2px 0}"
    ".signature{margin-top:50px;text-align:right}"
    ".signature-line{display:inline-block;width:250px;border-bottom:1px solid #000;"
    "min-height:40px;margin-bottom:6px;text-align:center}"
    ".signature-line img{max-height:48px}"
)

_DEFAULT_PLACEHOLDERS = [
    "hospital_name", "department", "patient_id", "encounter_id", "patient_name",
    "patient_age_sex", "doctor_name", "date", "visit_type",
    "physical_examination", "recommended_investigation", "signature",
]


def DEFAULT_PRESCRIPTION_TEMPLATE() -> DocumentTemplate:
    """The seeded Continental Hospitals "OP Note" design. Swap with another hospital's
    HTML by POSTing a new DocumentTemplate (it becomes the active default for its type)."""
    return DocumentTemplate(
        id="doc-default-prescription", hospital_id=None, doc_type="prescription",
        name="Continental Hospitals — OP Note", version=1, html=_DEFAULT_HTML, css=_DEFAULT_CSS,
        placeholders=_DEFAULT_PLACEHOLDERS, active=True,
    )
