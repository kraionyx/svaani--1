"""Batch-mode accuracy & latency benchmark — CLI.

Runs the golden clinical dataset through the real batch pipeline and prints a scorecard
(per-category recall, numeric fidelity, certainty, speaker attribution) plus a per-stage
latency table, then writes a JSON + Markdown report.

    # Where production stands now (uses the active extract prompt), live Gemini:
    python -m app.eval.bench --dataset clinical@v1 --template general_medicine

    # Prove the fix: A/B the original vs the strengthened extract prompt, side by side:
    python -m app.eval.bench --candidate --template general_medicine

    # Hermetic plumbing check (deterministic; will NOT reproduce the LLM flaws):
    python -m app.eval.bench --mock

Default run target is live Gemini (it reproduces the real accuracy flaws); ``--mock`` runs
the LLM-free deterministic path for CI.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.eval.clinical_runner import run_clinical_eval
from app.pipeline.prompts import EXTRACT_INSTRUCTION, EXTRACT_INSTRUCTION_V1_BASELINE

_ROOT = Path(__file__).resolve().parents[2]


def _fmt_pct(x: float) -> str:
    return f"{round(x * 100):3d}%"


def _bar(x: float, width: int = 20) -> str:
    n = round(x * width)
    return "█" * n + "·" * (width - n)


def _print_scorecard(title: str, result: dict) -> None:
    print(f"\n  {title}")
    print(f"  {'─' * 60}")
    for axis, score in result["scorecard"].items():
        print(f"  {axis:<34} {_bar(score)} {_fmt_pct(score)}")
    print(f"  {'─' * 60}")
    print(f"  {'OVERALL':<34} {_bar(result['overall'])} {_fmt_pct(result['overall'])}")


def _print_latency(result: dict) -> None:
    lat = result.get("latency", {})
    if not lat:
        return
    print(f"\n  Latency (ms, model={result['model']}, repeat={result['repeat']})")
    print(f"  {'stage':<10}{'p50':>8}{'p95':>8}{'mean':>8}{'max':>8}")
    for stage in ("analyze", "note", "risk", "total"):
        s = lat.get(stage)
        if s:
            print(f"  {stage:<10}{s['p50_ms']:>8}{s['p95_ms']:>8}{s['mean_ms']:>8}{s['max_ms']:>8}")


def _print_ab(baseline: dict, candidate: dict) -> None:
    print(f"\n  Baseline (original prompt)  vs  Candidate (strengthened prompt)")
    print(f"  {'─' * 70}")
    print(f"  {'axis':<34}{'baseline':>10}{'candidate':>12}{'Δ':>8}")
    for axis in candidate["scorecard"]:
        b = baseline["scorecard"].get(axis, 0.0)
        c = candidate["scorecard"][axis]
        d = c - b
        arrow = "▲" if d > 0.001 else ("▼" if d < -0.001 else " ")
        print(f"  {axis:<34}{_fmt_pct(b):>10}{_fmt_pct(c):>12}{arrow + _fmt_pct(abs(d)):>8}")
    print(f"  {'─' * 70}")
    db = candidate["overall"] - baseline["overall"]
    print(f"  {'OVERALL':<34}{_fmt_pct(baseline['overall']):>10}"
          f"{_fmt_pct(candidate['overall']):>12}{('▲' if db >= 0 else '▼') + _fmt_pct(abs(db)):>8}")


def _lost_facts(case: dict) -> list[str]:
    out = []
    for cat in case["categories"].values():
        for item in cat["items"]:
            if not item["hit"]:
                tag = "LOST" if not item["captured_anywhere"] else "misfiled"
                out.append(f"{cat['label']}: {item['name']} ({tag})")
            elif item.get("number_hit") is False:
                out.append(f"{cat['label']}: {item['name']} (number dropped)")
    return out


def _markdown(result: dict, *, baseline: dict | None = None) -> str:
    L = [f"# Batch-mode benchmark — {result['dataset']}", ""]
    L.append(f"- generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    L.append(f"- model: `{result['model']}`  ·  template: `{result['template_id']}`  ·  repeat: {result['repeat']}")
    L.append("")
    if baseline is not None:
        L += ["## Scorecard — baseline vs candidate (strengthened extract prompt)", "",
              "| Axis | Baseline | Candidate | Δ |", "|---|---:|---:|---:|"]
        for axis in result["scorecard"]:
            b = baseline["scorecard"].get(axis, 0.0)
            c = result["scorecard"][axis]
            L.append(f"| {axis} | {_fmt_pct(b)} | {_fmt_pct(c)} | {c - b:+.0%} |")
        L.append(f"| **OVERALL** | {_fmt_pct(baseline['overall'])} | {_fmt_pct(result['overall'])} "
                 f"| {result['overall'] - baseline['overall']:+.0%} |")
    else:
        L += ["## Scorecard", "", "| Axis | Score |", "|---|---:|"]
        for axis, score in result["scorecard"].items():
            L.append(f"| {axis} | {_fmt_pct(score)} |")
        L.append(f"| **OVERALL** | {_fmt_pct(result['overall'])} |")
    L.append("")
    lat = result.get("latency", {})
    if lat:
        L += ["## Latency (ms)", "", "| Stage | p50 | p95 | mean | max |", "|---|---:|---:|---:|---:|"]
        for stage in ("analyze", "note", "risk", "total"):
            s = lat.get(stage)
            if s:
                L.append(f"| {stage} | {s['p50_ms']} | {s['p95_ms']} | {s['mean_ms']} | {s['max_ms']} |")
        L.append("")
    L += ["## Per-case findings", ""]
    for case in result["cases"]:
        L.append(f"### {case['id']} — overall {_fmt_pct(case['overall'])}")
        lost = _lost_facts(case)
        if case["numeric_fidelity"]["lost"]:
            lost.append(f"numbers dropped: {', '.join(case['numeric_fidelity']['lost'])}")
        if case["certainty"]["upgraded_to_confirmed"]:
            lost.append(f"suspected→confirmed: {', '.join(case['certainty']['upgraded_to_confirmed'])}")
        if lost:
            L += [f"- {x}" for x in lost]
        else:
            L.append("- (no gaps)")
        L.append("")
    return "\n".join(L)


def _write_report(out_dir: Path, payload: dict, md: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    d = out_dir / stamp
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (d / "report.md").write_text(md, encoding="utf-8")
    return d


def main(argv: list[str] | None = None) -> int:
    # The scorecard uses box-drawing/bar glyphs; force UTF-8 so the Windows console
    # (cp1252 by default) doesn't choke. The report files are already UTF-8.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass

    p = argparse.ArgumentParser(description="Batch-mode accuracy & latency benchmark")
    p.add_argument("--dataset", default="clinical@v1")
    p.add_argument("--template", default="general_medicine",
                   help="template id to render against (default general_medicine; use 'ent' to "
                        "demonstrate the template-coverage gap)")
    p.add_argument("--mock", action="store_true", help="LLM-free deterministic run (CI)")
    p.add_argument("--candidate", action="store_true",
                   help="A/B the original vs strengthened extract prompt, side by side")
    p.add_argument("--repeat", type=int, default=1, help="pipeline runs per case (latency p50/p95)")
    p.add_argument("--out", default=str(_ROOT / "docs" / "benchmarks"))
    args = p.parse_args(argv)

    common = dict(dataset=args.dataset, template_id=args.template, mock=args.mock, repeat=args.repeat)

    if args.candidate:
        print("Running baseline (original extract prompt)…")
        baseline = run_clinical_eval(candidate_prompt=EXTRACT_INSTRUCTION_V1_BASELINE, **common)
        print("Running candidate (strengthened extract prompt)…")
        candidate = run_clinical_eval(candidate_prompt=EXTRACT_INSTRUCTION, **common)
        _print_ab(baseline, candidate)
        _print_latency(candidate)
        payload = {"mode": "candidate_ab", "baseline": baseline, "candidate": candidate}
        md = _markdown(candidate, baseline=baseline)
    else:
        print(f"Running benchmark ({'mock' if args.mock else 'live'})…")
        result = run_clinical_eval(**common)
        _print_scorecard(f"Scorecard — {args.dataset}", result)
        _print_latency(result)
        payload = {"mode": "single", "result": result}
        md = _markdown(result)

    d = _write_report(Path(args.out), payload, md)
    print(f"\n  report → {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
