"""Guards on the audio-upload route: silence/empty audio must error, not blank-note.

Hermetic: forces the mock STT so the route never touches the live Sarvam provider
even when a real key is present in ``.env``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.stt.sarvam import MockSarvamSTT

client = TestClient(app)


def _new_session() -> str:
    r = client.post("/sessions", json={"template_id": "soap"})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def test_empty_audio_rejected():
    sid = _new_session()
    r = client.post(f"/sessions/{sid}/audio", files={"file": ("empty.wav", b"", "audio/wav")})
    assert r.status_code == 422
    assert "no audible speech" in r.json()["detail"]


def test_nonempty_audio_succeeds(monkeypatch):
    # Force mock STT (canned ENT transcript) regardless of .env credentials.
    monkeypatch.setattr("app.main.get_stt", lambda settings: MockSarvamSTT())
    sid = _new_session()
    payload = b"\x00" * 2048  # >= _MIN_AUDIO_BYTES; mock ignores content
    r = client.post(f"/sessions/{sid}/audio", files={"file": ("consult.wav", payload, "audio/wav")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == sid
    assert "note_markdown" in body
