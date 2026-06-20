"""Batch-mode benchmark runner — drives the REAL accuracy path and scores it.

Each golden case is built into a diarized ``RawTranscript`` (``build_raw``) and run through
the full ``run_pipeline`` — the same clean → extract → ground → note → risk path batch mode
uses — then scored by ``app.eval.clinical_scorer``. Per-stage latency comes from
``PipelineResult.timings_ms``; with ``repeat>1`` we aggregate p50/p95 across runs.

A candidate ``extract`` prompt is injected via the PromptProvider override (cleared in a
``finally``), so a prompt change can be A/B-scored WITHOUT deploying it — exactly the
mechanism the Goal-13 improvement flow already uses (see ``app/eval/runner.py``).
"""
from __future__ import annotations

from app.config import Settings, get_settings
from app.eval.clinical_scorer import aggregate, score_case
from app.eval.dataset import build_raw, load_dataset
from app.llm.base import DisabledLLM, MedicalLLM, get_llm
from app.pipeline.orchestrator import run_pipeline
from app.pipeline.prompt_provider import get_prompt_provider
from app.templates.registry import get_registry


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _latency_summary(timings: list[dict]) -> dict:
    """p50/p95/mean/max per stage (ms) across every pipeline run."""
    stages = ["analyze", "note", "risk", "total"]
    out: dict[str, dict] = {}
    for stage in stages:
        vals = [float(t[stage]) for t in timings if stage in t]
        if not vals:
            continue
        out[stage] = {
            "n": len(vals),
            "p50_ms": round(_percentile(vals, 0.50)),
            "p95_ms": round(_percentile(vals, 0.95)),
            "mean_ms": round(sum(vals) / len(vals)),
            "max_ms": round(max(vals)),
        }
    return out


def run_clinical_eval(
    dataset: str = "clinical@v1",
    *,
    template_id: str = "general_medicine",
    candidate_prompt: str | None = None,
    llm: MedicalLLM | None = None,
    mock: bool = False,
    repeat: int = 1,
    settings: Settings | None = None,
) -> dict:
    """Score ``dataset`` through the batch pipeline and return an aggregate scorecard.

    ``mock=True`` forces the deterministic, LLM-free path (CI / plumbing — it will NOT
    reproduce the LLM accuracy flaws). ``candidate_prompt`` overrides the ``extract`` prompt
    for this run only.
    """
    settings = settings or get_settings()
    template = get_registry().get(template_id)
    if llm is None:
        llm = DisabledLLM() if mock else get_llm(settings)

    provider = get_prompt_provider()
    if candidate_prompt is not None:
        provider.set_override({"extract": candidate_prompt})
    try:
        cases = load_dataset(dataset)
        case_results: list[dict] = []
        all_timings: list[dict] = []
        for case in cases:
            runs: list[dict] = []
            case_timings: list[dict] = []
            for _ in range(max(1, repeat)):
                raw = build_raw(case)  # fresh: run_pipeline mutates segment roles in place
                result = run_pipeline(raw, template, llm=llm, settings=settings)
                case_timings.append(result.timings_ms)
                runs.append(score_case(case, result.extraction, result.profile))
            # LLMs are non-deterministic even at temp 0, so average the headline/overall
            # across repeats; keep the first run's detailed items for the report.
            scored = runs[0]
            if len(runs) > 1:
                axes = scored["headline"].keys()
                scored["headline"] = {
                    a: round(sum(r["headline"].get(a, 0.0) for r in runs) / len(runs), 3) for a in axes
                }
                scored["overall"] = round(sum(r["overall"] for r in runs) / len(runs), 3)
                scored["overall_runs"] = [r["overall"] for r in runs]
            scored["n_runs"] = len(runs)
            scored["latency"] = _latency_summary(case_timings)
            case_results.append(scored)
            all_timings.extend(case_timings)
    finally:
        if candidate_prompt is not None:
            provider.clear_override()

    out = aggregate(case_results)
    out.update({
        "dataset": dataset,
        "template_id": template_id,
        "mock": mock,
        "model": "mock" if mock else settings.gemini_model,
        "repeat": repeat,
        "candidate_prompt": bool(candidate_prompt),
        "latency": _latency_summary(all_timings),
        "cases": case_results,
    })
    return out
