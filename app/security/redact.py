"""PHI redaction.

Uses Microsoft Presidio when installed; otherwise falls back to a regex redactor
covering common direct identifiers (email, phone, long digit runs / MRNs, dates).
Apply before sending text to any external service where PHI minimization is
required by policy.
"""
from __future__ import annotations

import re

_REGEX_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("PHONE", re.compile(r"\b(?:\+?\d[\d\-\s]{7,}\d)\b")),
    ("DATE", re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")),
    ("ID_NUMBER", re.compile(r"\b\d{6,}\b")),
]


def _regex_redact(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    redacted = text
    for label, pattern in _REGEX_PATTERNS:
        if pattern.search(redacted):
            found.append(label)
            redacted = pattern.sub(f"<{label}>", redacted)
    return redacted, found


def redact_phi(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, entity_types_found)."""
    try:
        from presidio_analyzer import AnalyzerEngine  # deferred / optional

        analyzer = AnalyzerEngine()
        results = analyzer.analyze(text=text, language="en")
        if not results:
            return text, []
        # Redact from the end so offsets stay valid.
        redacted = text
        for r in sorted(results, key=lambda x: x.start, reverse=True):
            redacted = redacted[: r.start] + f"<{r.entity_type}>" + redacted[r.end:]
        return redacted, sorted({r.entity_type for r in results})
    except Exception:
        return _regex_redact(text)
