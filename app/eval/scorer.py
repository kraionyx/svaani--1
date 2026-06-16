"""Scoring for the eval harness (Goal 9).

Compares a resolved ConversationProfile against a golden case's expectations and produces
per-case pass/fail + an aggregate. The headline metric is **attribution** — did the scribe
identify the right patient(s), the right conversation kind, and the right speaker roles —
because that is exactly what the multi-speaker hardening must not regress.
"""
from __future__ import annotations

from app.eval.dataset import GoldenCase
from app.schemas.intelligence import ConversationProfile


def score_case(case: GoldenCase, profile: ConversationProfile) -> dict:
    exp = case.expect
    checks: dict[str, bool] = {}
    if "referenced_patient" in exp:
        checks["referenced_patient"] = profile.referenced_patient == exp["referenced_patient"]
    if "kind" in exp:
        checks["kind"] = profile.kind.value == exp["kind"]
    if "referenced_subjects" in exp:
        got = sorted(s.label for s in profile.referenced_subjects)
        checks["referenced_subjects"] = got == sorted(exp["referenced_subjects"])
    if "has_roles" in exp:
        roles = {s.role.value for s in profile.speakers}
        checks["has_roles"] = all(r in roles for r in exp["has_roles"])
    if "is_complex" in exp:
        checks["is_complex"] = profile.is_complex is exp["is_complex"]
    return {"id": case.id, "passed": all(checks.values()) if checks else True, "checks": checks}


def aggregate(case_results: list[dict]) -> dict:
    n = len(case_results)
    passed = sum(1 for r in case_results if r["passed"])
    return {
        "n_cases": n,
        "attribution": round(passed / n, 3) if n else 0.0,
        "passed": passed == n,
        "failures": [r["id"] for r in case_results if not r["passed"]],
    }
