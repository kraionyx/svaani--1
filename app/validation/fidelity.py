"""Content-level fact verification — the layer above grounding.

Grounding (``app.validation.grounding``) proves an extracted item *cites a span that
exists*. It does NOT prove the item's content actually matches what that span says —
so a model that "normalizes" a spoken ``1 mg`` into a typical ``40 mg``, or renames
``Irtrizol`` to ``Itraconazole``, still passes grounding because ``seg-0008`` is real.

This module closes that gap for the safety-critical fields: it checks that a
medication's name and dose literally appear in the text of the span(s) it cites, and
reports any that don't so the reviewing clinician sees the mismatch. It never edits
or drops content (a genuine ASR variant could be a false positive) — it flags.
"""
from __future__ import annotations

import re

from app.schemas.clinical import ClinicalExtraction
from app.schemas.transcript import CleanTranscript


def _norm(s: str) -> str:
    """Lowercase and strip non-alphanumerics so '40 mg' ~ '40mg' and 'Itra-conazole' ~ 'itraconazole'."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _dose_in(dose: str, haystack_norm: str) -> bool:
    # Compare the numeric+unit core verbatim; '40 mg' -> '40mg' must occur in the span.
    return _norm(dose) in haystack_norm if dose else True


def _name_in(name: str, haystack_norm: str) -> bool:
    # A drug name matches if any of its alphabetic tokens (>=4 chars) occurs in the span;
    # this tolerates spacing/ASR spelling drift without accepting a wholesale rename.
    tokens = [_norm(t) for t in re.split(r"\s+", name or "") if len(_norm(t)) >= 4]
    if not tokens:
        return bool(_norm(name)) and _norm(name) in haystack_norm
    return any(t in haystack_norm for t in tokens)


def verify_medication_fidelity(
    extraction: ClinicalExtraction, clean: CleanTranscript
) -> tuple[list[str], list[str]]:
    """Return ``(verified, mismatched)`` human-readable labels for medication content.

    A medication is *mismatched* when its drug name or its dose cannot be found in the
    transcript span(s) it cites — i.e. the value was inferred or normalized, not heard.
    """
    span_text = {s.id: (s.text or "") for s in clean.segments}
    verified: list[str] = []
    mismatched: list[str] = []

    for med in extraction.medications_discussed:
        cited = " ".join(span_text.get(sid, "") for sid in med.provenance.span_ids)
        cited_norm = _norm(cited)
        label = f"{med.name}" + (f" {med.dose}" if med.dose else "")
        problems: list[str] = []
        if not _name_in(med.name, cited_norm):
            problems.append(f"name '{med.name}' not heard in cited span(s)")
        if med.dose and not _dose_in(med.dose, cited_norm):
            problems.append(f"dose '{med.dose}' not heard in cited span(s)")
        if problems:
            # Leave a trace on the item itself, and report it.
            med.provenance.note = "; ".join(problems)
            mismatched.append(f"medication:{label} — {'; '.join(problems)}")
        else:
            verified.append(f"medication:{label} ✓ matches transcript")

    return verified, mismatched
