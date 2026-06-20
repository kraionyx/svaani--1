"""Clinical-extraction scorer for the batch-mode benchmark.

Scores a ``ClinicalExtraction`` (the structured JSON — NOT the rendered note, so a
template that lacks a section can't be blamed for the model losing a fact) against a
golden case's expected facts. Deterministic and transparent: every fact is matched by
case-insensitive alias substring, every number by a token-boundary check, so the score
is auditable and does not grade the model with another model.

Three things the team flagged as the failure modes are first-class metrics here:
  • per-category recall (esp. past_medical_history / family_history / investigations),
  • numeric fidelity (did EF 48%, LDL 168, '8 years', etc. survive verbatim),
  • certainty (a SUSPECTED finding must land in `assessment`, not `diagnosis`).

Strict recall asks "did the fact land in the field the note section reads?" (== what the
doctor sees). Lenient recall asks "was it captured anywhere?" — the gap between the two
is the *misfiled* (vs *lost*) rate, which localizes the fix.
"""
from __future__ import annotations

import json
import re

from app.eval.dataset import GoldenCase
from app.schemas.clinical import ClinicalExtraction
from app.schemas.intelligence import ConversationProfile

#: Category in the golden `expect.facts` → the extraction data-map keys whose text the
#: note section for that category renders from. The first key is the canonical one.
_CATEGORY_FIELDS: dict[str, list[str]] = {
    "chief_complaints": ["chief_complaints", "history_of_present_illness"],
    "past_medical_history": ["past_medical_history"],
    "family_history": ["family_history"],
    "investigations": ["investigations"],
    # Recall = "captured as a clinical conclusion" — a conclusion in either assessment or
    # diagnosis counts. WHETHER it is in the right one (certainty) is scored separately, so a
    # safe placement (confirmed finding filed under assessment) isn't double-penalized.
    "assessment_suspected": ["assessment", "diagnosis"],
    "diagnosis_confirmed": ["diagnosis", "assessment"],
    "treatment_plan": ["treatment_plan", "medications_discussed"],
    "differentials": ["assessment", "investigations"],
}

#: Human labels for the headline scorecard (mirrors the team's failure table).
CATEGORY_LABELS: dict[str, str] = {
    "chief_complaints": "Symptoms",
    "past_medical_history": "Past Medical History / Risk Factors",
    "family_history": "Family History",
    "investigations": "Investigations",
    "assessment_suspected": "Assessment (suspected)",
    "diagnosis_confirmed": "Diagnosis (confirmed)",
    "treatment_plan": "Treatment Plan",
    "differentials": "Differentials",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _field_text(data: dict, keys: list[str]) -> str:
    """Concatenated, normalized text of the given extraction data-map keys."""
    return _norm(" ".join(json.dumps(data.get(k), ensure_ascii=False) for k in keys if data.get(k)))


def _number_present(num: str, text: str) -> bool:
    """True if `num` appears as a standalone numeric token (so '8' != '48'/'168')."""
    return re.search(rf"(?<![\d.]){re.escape(num)}(?![\d.])", text) is not None


def _alias_hit(aliases: list[str], text: str) -> bool:
    return any(_norm(a) in text for a in aliases)


def _score_fact(fact: dict, field_text: str, all_text: str) -> dict:
    """Match one expected fact against the canonical field and the whole extraction."""
    aliases = fact.get("aliases", [])
    strict = _alias_hit(aliases, field_text)
    lenient = strict or _alias_hit(aliases, all_text)
    # Qualifier (e.g. TMT 'positive') must be preserved for full credit.
    must = fact.get("must")
    if strict and must and _norm(must) not in field_text:
        strict = False
    # Numeric fidelity: every required number must survive as a token in the field.
    numbers = fact.get("numbers", [])
    nums_ok = [n for n in numbers if _number_present(n, field_text if strict else all_text)]
    number_hit = (len(nums_ok) == len(numbers)) if numbers else None
    return {
        "name": fact.get("name", aliases[0] if aliases else "?"),
        "hit": strict,                       # field-correct (what the note shows)
        "captured_anywhere": lenient,        # captured but possibly misfiled
        "has_numbers": bool(numbers),
        "number_hit": number_hit,
    }


def score_case(
    case: GoldenCase, extraction: ClinicalExtraction, profile: ConversationProfile | None
) -> dict:
    exp = case.expect
    data = extraction.to_data_map()
    all_text = _norm(json.dumps(data, ensure_ascii=False))

    # ── Per-category recall ──────────────────────────────────────────────────
    categories: dict[str, dict] = {}
    facts_block = exp.get("facts", {})
    for cat, facts in facts_block.items():
        field_text = _field_text(data, _CATEGORY_FIELDS.get(cat, [cat]))
        items = [_score_fact(f, field_text, all_text) for f in facts]
        hit = sum(1 for i in items if i["hit"])
        anywhere = sum(1 for i in items if i["captured_anywhere"])
        categories[cat] = {
            "label": CATEGORY_LABELS.get(cat, cat),
            "total": len(items),
            "hit": hit,
            "captured_anywhere": anywhere,
            "recall": round(hit / len(items), 3) if items else 1.0,
            "lenient_recall": round(anywhere / len(items), 3) if items else 1.0,
            "items": items,
        }

    # ── Numeric fidelity (key numbers that must survive verbatim anywhere) ────
    must_nums = exp.get("numbers_must_survive", [])
    survived = [n for n in must_nums if _number_present(n, all_text)]
    numeric = {
        "total": len(must_nums),
        "survived": len(survived),
        "lost": [n for n in must_nums if n not in survived],
        "score": round(len(survived) / len(must_nums), 3) if must_nums else 1.0,
    }

    # ── Certainty: a SUSPECTED finding must sit in `assessment`, NOT `diagnosis` ──
    # The dangerous error is over-claiming — rendering a possibility as a confirmed
    # diagnosis. Score = how many suspected items are correctly placed in assessment,
    # halved if any was upgraded into the diagnosis field.
    assess_text = _field_text(data, ["assessment"])
    dx_only_text = _field_text(data, ["diagnosis"])
    suspected = facts_block.get("assessment_suspected", [])
    placed = sum(1 for f in suspected if _alias_hit(f.get("aliases", []), assess_text))
    upgraded = [f.get("name", "?") for f in suspected if _alias_hit(f.get("aliases", []), dx_only_text)]
    placement = (placed / len(suspected)) if suspected else 1.0
    certainty = {
        "suspected_in_assessment": round(placement, 3),
        "upgraded_to_confirmed": upgraded,   # suspected dx wrongly rendered as confirmed
        "score": round(placement * (0.5 if upgraded else 1.0), 3),
    }

    # ── Speaker attribution ──────────────────────────────────────────────────
    attribution = _score_attribution(exp, profile)

    # ── Headline: category recalls + the cross-cutting axes ──────────────────
    headline = {categories[c]["label"]: categories[c]["recall"] for c in categories}
    headline["Numeric Preservation"] = numeric["score"]
    headline["Certainty"] = certainty["score"]
    headline["Speaker Attribution"] = attribution["score"]

    overall = round(sum(headline.values()) / len(headline), 3) if headline else 0.0
    return {
        "id": case.id,
        "categories": categories,
        "numeric_fidelity": numeric,
        "certainty": certainty,
        "attribution": attribution,
        "headline": headline,
        "overall": overall,
    }


def _score_attribution(exp: dict, profile: ConversationProfile | None) -> dict:
    """Attribution = referenced_patient correct + each expected clinical role resolved.

    Resolution groups speakers by their resolved ROLE (``SpeakerProfile.speaker_label`` is
    the role value, see ``app.pipeline.subjects``), so we check the *set* of resolved roles
    against ``expect.has_roles`` rather than a diarized-label → role map.
    """
    if profile is None:
        return {"score": 0.0, "checks": {}, "note": "no profile (subject resolution off)"}
    checks: dict[str, bool] = {}
    if "referenced_patient" in exp:
        checks["referenced_patient"] = profile.referenced_patient == exp["referenced_patient"]
    resolved_roles = {s.role.value for s in profile.speakers}
    for want in exp.get("has_roles", []):
        checks[f"role:{want}"] = want in resolved_roles
    score = round(sum(checks.values()) / len(checks), 3) if checks else 1.0
    return {"score": score, "checks": checks, "resolved_roles": sorted(resolved_roles)}


def aggregate(case_results: list[dict]) -> dict:
    """Mean each headline axis across cases → the dataset scorecard."""
    if not case_results:
        return {"n_cases": 0, "scorecard": {}, "overall": 0.0}
    axes = list(case_results[0]["headline"].keys())
    scorecard = {
        axis: round(sum(r["headline"].get(axis, 0.0) for r in case_results) / len(case_results), 3)
        for axis in axes
    }
    overall = round(sum(r["overall"] for r in case_results) / len(case_results), 3)
    return {"n_cases": len(case_results), "scorecard": scorecard, "overall": overall}
