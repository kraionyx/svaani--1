"""Offline eval runner (Goal 9 — the engine behind the improvement pipeline).

Runs a (optionally candidate) prompt over a golden dataset through the REAL accuracy path
and scores it, WITHOUT deploying anything: the candidate prompt is injected via the
PromptProvider's override (cleared afterward), never written to a prompt_versions row.
Deterministic at temp=0; with no LLM it still validates rule-based attribution (regression
detection). A passing run is a precondition for the human-gated deploy step.
"""
from __future__ import annotations

from app.config import Settings, get_settings
from app.eval.dataset import build_raw, load_dataset
from app.eval.scorer import aggregate, score_case
from app.llm.base import MedicalLLM
from app.pipeline.complexity import assess_complexity
from app.pipeline.prompt_provider import get_prompt_provider
from app.pipeline.subjects import resolve_relationships
from app.stt.doctor_detect import assign_clinical_roles


def run_eval(
    dataset: str = "multispeaker@v1",
    *,
    candidate_prompt: str | None = None,
    prompt_name: str = "relationship",
    llm: MedicalLLM | None = None,
    settings: Settings | None = None,
) -> dict:
    """Score ``dataset`` (optionally with a candidate prompt for ``prompt_name``) and return
    an aggregate ``{dataset, n_cases, attribution, passed, failures, cases}``."""
    settings = settings or get_settings()
    cases = load_dataset(dataset)
    provider = get_prompt_provider()
    if candidate_prompt:
        provider.set_override({prompt_name: candidate_prompt})
    try:
        results = []
        for case in cases:
            raw = build_raw(case)
            assign_clinical_roles(raw)
            profile = resolve_relationships(raw, llm)
            assess_complexity(profile, raw, settings)
            results.append(score_case(case, profile))
    finally:
        if candidate_prompt:
            provider.clear_override()
    out = aggregate(results)
    out["dataset"] = dataset
    out["prompt_name"] = prompt_name
    out["cases"] = results
    return out
