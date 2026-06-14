"""Medical Understanding LLM — provider-agnostic interface.

The pipeline depends only on ``MedicalLLM``; the concrete provider (Gemini on
Vertex AI today) is selected by ``get_llm`` and is fully swappable. When no provider
is configured, ``DisabledLLM`` is returned and every pipeline stage falls back to a
deterministic, rule-based path — so the app and tests run with no credentials.
"""
from __future__ import annotations

from typing import Iterator, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from app.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """Raised when a stage asks a DisabledLLM to generate."""


@runtime_checkable
class MedicalLLM(Protocol):
    @property
    def available(self) -> bool: ...

    def generate_structured(self, prompt: str, schema: type[T], *, system: str | None = None) -> T:
        """Return an instance of ``schema`` validated from the model's JSON output."""

    def generate_text(self, prompt: str, *, system: str | None = None) -> str: ...

    def generate_text_stream(self, prompt: str, *, system: str | None = None) -> Iterator[str]:
        """Yield text chunks as the model produces them (for streaming prose to the UI)."""


class DisabledLLM:
    """No-op provider used when nothing is configured."""

    available = False

    def generate_structured(self, prompt: str, schema: type[T], *, system: str | None = None) -> T:
        raise LLMUnavailable(
            "No medical LLM configured. Set SCRIBE_VERTEX_PROJECT and install google-genai."
        )

    def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        raise LLMUnavailable(
            "No medical LLM configured. Set SCRIBE_VERTEX_PROJECT and install google-genai."
        )

    def generate_text_stream(self, prompt: str, *, system: str | None = None) -> Iterator[str]:
        raise LLMUnavailable(
            "No medical LLM configured. Set SCRIBE_VERTEX_PROJECT and install google-genai."
        )


def get_llm(settings: Settings | None = None) -> MedicalLLM:
    settings = settings or get_settings()
    if settings.use_vertex:
        try:
            from app.llm.vertex_gemini import VertexGeminiLLM

            return VertexGeminiLLM(settings)
        except Exception:  # SDK missing or client init failure → degrade gracefully
            return DisabledLLM()
    return DisabledLLM()
