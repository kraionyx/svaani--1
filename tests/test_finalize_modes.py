"""Goal 3 — the inference-mode choice genuinely changes the streaming flow.

Drives the WebSocket finalize step (app.audio.ws._finalize) directly with a fake socket and a
stubbed diarizer, asserting each mode behaves differently:
  • real-time → never diarizes (live draft only);
  • batch     → one diarized pass, no live-then-refine;
  • auto       → drafts, then refines + banners ONLY when the diarized consult is complex.

Deterministic: no real LLM (DisabledLLM), no real STT (diarizer stubbed), in-memory store.
"""
from __future__ import annotations

import asyncio

from app.audio import ws as wsmod
from app.config import get_settings
from app.llm.base import DisabledLLM
from app.schemas.session import ConsultationSession, ReviewState
from app.schemas.transcript import RawTranscript, SpeakerRole, TranscriptSegment
from app.store import SessionStore


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, m: dict) -> None:
        self.sent.append(m)


def _seg(i, spk, text, s, e, conf=0.95) -> TranscriptSegment:
    return TranscriptSegment(id=f"seg-{i:04d}", speaker=spk, text=text, start_ms=s, end_ms=e, confidence=conf)


def _complex(sid: str) -> RawTranscript:
    # 3 speakers + overlap + an unresolved speaker → complexity ≥ 0.6.
    return RawTranscript(session_id=sid, segments=[
        _seg(1, SpeakerRole.DOCTOR, "What happened?", 0, 1500),
        _seg(2, SpeakerRole.PATIENT, "My son has had fever for three days.", 1200, 3000),
        _seg(3, SpeakerRole.OTHER, "And he is coughing a lot too.", 2800, 4500, 0.55),
        _seg(4, SpeakerRole.DOCTOR, "Is he vomiting?", 4300, 5200),
    ])


def _simple(sid: str) -> RawTranscript:
    return RawTranscript(session_id=sid, segments=[
        _seg(1, SpeakerRole.DOCTOR, "What brings you in?", 0, 1500),
        _seg(2, SpeakerRole.PATIENT, "I have a sore throat.", 1600, 3000),
    ])


def _run(monkeypatch, *, auto: bool, manual: str, diar) -> tuple[int, list[str]]:
    monkeypatch.setattr("app.pipeline.orchestrator.get_llm", lambda settings=None: DisabledLLM())
    calls = {"n": 0}

    async def fake_diarize(settings, session_id, pcm):
        calls["n"] += 1
        return diar(session_id) if diar else None

    monkeypatch.setattr(wsmod, "_diarize", fake_diarize)

    store = SessionStore()
    session = ConsultationSession(
        session_id="t", template_id="soap", state=ReviewState.LISTENING,
        auto_mode=auto, manual_mode=manual,
    )
    store.create(session)
    ws = FakeWS()
    live = [("seg-0001", "Patient reports throat pain for two days.")]
    asyncio.run(wsmod._finalize(ws, store, get_settings(), session, b"\x00" * 4096, live))
    return calls["n"], [m.get("type") for m in ws.sent]


def test_realtime_never_diarizes(monkeypatch):
    n, types = _run(monkeypatch, auto=False, manual="realtime", diar=_complex)
    assert n == 0                                   # the whole point: no batch pass
    assert "draft_ready" in types
    assert "refined" not in types and "mode_switch" not in types


def test_batch_is_single_diarized_pass(monkeypatch):
    n, types = _run(monkeypatch, auto=False, manual="batch", diar=_simple)
    assert n == 1                                   # diarized exactly once
    assert "draft_ready" in types
    assert "refined" not in types                   # not a draft-then-refine


def test_auto_simple_keeps_draft(monkeypatch):
    n, types = _run(monkeypatch, auto=True, manual="realtime", diar=_simple)
    assert n == 1                                   # diarized to judge complexity
    assert "draft_ready" in types
    assert "refined" not in types and "mode_switch" not in types  # simple → keep the draft


def test_auto_complex_refines_and_banners(monkeypatch):
    n, types = _run(monkeypatch, auto=True, manual="realtime", diar=_complex)
    assert n == 1
    assert "draft_ready" in types                   # draft shown first
    assert "refined" in types                       # then replaced with the accurate pass
    assert "mode_switch" in types                   # and the "switched to Batch" banner


def test_hybrid_always_refines_without_banner(monkeypatch):
    # Even a SIMPLE consult is sharpened in hybrid (best balance) — and no auto-switch banner.
    n, types = _run(monkeypatch, auto=False, manual="hybrid", diar=_simple)
    assert n == 1
    assert "draft_ready" in types                   # instant draft (fast reply)
    assert "refined" in types                       # always sharpened (accuracy)
    assert "mode_switch" not in types               # hybrid isn't an auto-escalation
