"""Goal 3 & 5 — real-time vs batch decision + the notice-bar payload.

The streaming WS already runs a hybrid fast-then-refine flow (live draft, then a
batch-diarized refine). This module decides which mode is *authoritative* for a given
consult:

  • Manual: the doctor's fixed choice (``default_inference_mode``).
  • Auto (``auto_inference_mode``): the complexity classifier (Goal 2) chooses — simple
    consults stay real-time; complex ones escalate to batch for accuracy, with a
    non-intrusive notice (Goal 5).

Pure decision logic; no side effects.
"""
from __future__ import annotations

from app.config import Settings
from app.schemas.intelligence import ConversationProfile
from app.schemas.review import InferenceMode


def decide_mode(
    profile: ConversationProfile | None,
    settings: Settings,
    *,
    auto: bool | None = None,
    manual: str | None = None,
) -> InferenceMode:
    """Resolve the authoritative inference mode for a consult (Goal 3).

    Precedence, per the doctor's pre-consult choice:
      • ``auto`` (Auto AI Mode): the complexity classifier picks — simple → realtime,
        complex → batch. When ``auto`` is ``None`` we fall back to the server-wide
        ``auto_inference_mode`` default.
      • ``manual`` ("realtime" | "batch"): the doctor's explicit pick, used when auto is off.
      • otherwise the server-wide ``default_inference_mode``.
    """
    use_auto = settings.auto_inference_mode if auto is None else auto
    if use_auto:
        if profile is not None and profile.is_complex:
            return InferenceMode.AUTO_BATCH
        return InferenceMode.AUTO_REALTIME
    if manual == "hybrid":
        return InferenceMode.HYBRID
    if manual == "batch":
        return InferenceMode.BATCH
    if manual == "realtime":
        return InferenceMode.REALTIME
    return InferenceMode.BATCH if settings.default_inference_mode == "batch" else InferenceMode.REALTIME


def split_mode_choice(mode: str | None, *, legacy_auto: bool = False) -> tuple[bool, str]:
    """Map a pre-consult mode choice → (auto_mode, manual_mode).

    ``mode`` is one of 'auto' | 'realtime' | 'batch' | 'hybrid'. ``legacy_auto`` is the older
    boolean form, used only when ``mode`` is omitted.
    """
    choice = (mode or ("auto" if legacy_auto else "realtime")).lower()
    return choice == "auto", (choice if choice in ("realtime", "batch", "hybrid") else "realtime")


def is_batch(mode: InferenceMode) -> bool:
    return mode in (InferenceMode.BATCH, InferenceMode.AUTO_BATCH)


def mode_switch_notice(profile: ConversationProfile, mode: InferenceMode) -> dict:
    """Payload for the Goal-5 notice bar when Auto mode escalates to batch."""
    reason = "; ".join(profile.complexity_signals[:2]) or "increased conversation complexity"
    return {
        "type": "mode_switch",
        "from": "realtime",
        "to": "batch",
        "auto": mode is InferenceMode.AUTO_BATCH,
        "reason": reason,
        "message": (
            "Multiple speakers detected. Switching to Batch Processing for improved "
            "clinical accuracy. Responses may be delayed slightly."
        ),
        "est_delay_s": [3, 5],
    }
