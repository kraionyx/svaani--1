"""Gemini on Vertex AI — the selected Medical Understanding provider.

Uses Vertex controlled generation so the model's output validates against our
Pydantic schemas. temperature=0 keeps structuring deterministic.

Every generate call logs latency, token counts, and cost estimate to Supabase
via the non-blocking logging service (fire-and-forget, never blocks the pipeline).
"""
from __future__ import annotations

import time
from typing import Iterator, TypeVar

from pydantic import BaseModel

from app.config import Settings

T = TypeVar("T", bound=BaseModel)

# Thread-local agent context: set by pipeline stages so the log entry names the stage.
import threading
_agent_ctx = threading.local()


def set_agent(name: str | None) -> None:
    """Set the current pipeline stage name for AI analytics tagging."""
    _agent_ctx.name = name


def get_agent() -> str | None:
    return getattr(_agent_ctx, "name", None)


class VertexGeminiLLM:
    _thinking_unsupported: set[str] = set()

    def __init__(self, settings: Settings) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self.settings = settings
        if settings.vertex_api_key:
            self.client = genai.Client(vertexai=True, api_key=settings.vertex_api_key, http_options={"timeout": 30.0})
        else:
            self.client = genai.Client(
                vertexai=True,
                project=settings.vertex_project,
                location=settings.vertex_location,
                http_options={"timeout": 30.0}
            )

    @property
    def available(self) -> bool:
        return True

    def _thinking_config(self):
        thinking_cls = getattr(self._types, "ThinkingConfig", None)
        if thinking_cls is None or self.settings.gemini_model in self._thinking_unsupported:
            return None
        return thinking_cls(thinking_budget=self.settings.llm_thinking_budget)

    @staticmethod
    def _is_thinking_error(exc: Exception) -> bool:
        return "thinking_budget" in str(exc).lower()

    def _config(self, *, system: str | None, schema: type[BaseModel] | None):
        kwargs = dict(
            temperature=self.settings.llm_temperature,
            max_output_tokens=self.settings.llm_max_output_tokens,
            system_instruction=system,
            response_mime_type="application/json" if schema else None,
            response_schema=schema,
        )
        thinking = self._thinking_config()
        if thinking is not None:
            kwargs["thinking_config"] = thinking
        return self._types.GenerateContentConfig(**kwargs)

    def _generate(self, prompt: str, *, system: str | None, schema: type[BaseModel] | None):
        """generate_content with a self-healing thinking_budget retry + AI analytics logging."""
        t0 = time.perf_counter()
        retry_count = 0
        exc_captured = None
        resp = None
        try:
            try:
                resp = self.client.models.generate_content(
                    model=self.settings.gemini_model, contents=prompt,
                    config=self._config(system=system, schema=schema),
                )
            except Exception as exc:
                if self._is_thinking_error(exc) and \
                        self.settings.gemini_model not in self._thinking_unsupported:
                    VertexGeminiLLM._thinking_unsupported.add(self.settings.gemini_model)
                    retry_count = 1
                    resp = self.client.models.generate_content(
                        model=self.settings.gemini_model, contents=prompt,
                        config=self._config(system=system, schema=schema),
                    )
                else:
                    exc_captured = exc
                    raise
        except Exception as exc:
            exc_captured = exc
            raise
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            self._log_ai(resp, latency_ms=latency_ms, retry_count=retry_count,
                         success=exc_captured is None,
                         error_message=str(exc_captured) if exc_captured else None)
        return resp

    def _log_ai(self, resp, *, latency_ms: int, retry_count: int,
                success: bool, error_message: str | None) -> None:
        try:
            from app.logging_service import get_logging_service
            prompt_tokens = completion_tokens = total_tokens = None
            if resp is not None:
                um = getattr(resp, "usage_metadata", None)
                if um:
                    prompt_tokens     = getattr(um, "prompt_token_count", None)
                    completion_tokens = getattr(um, "candidates_token_count", None)
                    total_tokens      = getattr(um, "total_token_count", None)
            get_logging_service().log_ai(
                model=self.settings.gemini_model,
                agent=get_agent(),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                success=success,
                retry_count=retry_count,
                error_message=error_message,
            )
        except Exception:
            pass  # AI logging must never break the pipeline

    def generate_structured(self, prompt: str, schema: type[T], *, system: str | None = None) -> T:
        resp = self._generate(prompt, system=system, schema=schema)
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        return schema.model_validate_json(resp.text)

    def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        return self._generate(prompt, system=system, schema=None).text or ""

    def generate_text_stream(self, prompt: str, *, system: str | None = None) -> Iterator[str]:
        """Stream with self-healing thinking_budget retry + AI analytics for the full stream."""
        t0 = time.perf_counter()
        retry_count = 0
        total_chunks = 0

        def _open() -> Iterator[str]:
            nonlocal total_chunks
            stream = self.client.models.generate_content_stream(
                model=self.settings.gemini_model, contents=prompt,
                config=self._config(system=system, schema=None),
            )
            for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    total_chunks += 1
                    yield text

        try:
            yield from _open()
        except Exception as exc:
            if self._is_thinking_error(exc) and \
                    self.settings.gemini_model not in self._thinking_unsupported:
                VertexGeminiLLM._thinking_unsupported.add(self.settings.gemini_model)
                retry_count = 1
                yield from _open()
            else:
                raise
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            self._log_ai(None, latency_ms=latency_ms, retry_count=retry_count,
                         success=True, error_message=None)
