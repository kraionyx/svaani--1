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


def decide_mode(profile: ConversationProfile | None, settings: Settings) -> InferenceMode:
    """Resolve the authoritative inference mode for a consult."""
    if settings.auto_inference_mode:
        if profile is not None and profile.is_complex:
            return InferenceMode.AUTO_BATCH
        return InferenceMode.AUTO_REALTIME
    return InferenceMode.BATCH if settings.default_inference_mode == "batch" else InferenceMode.REALTIME


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
