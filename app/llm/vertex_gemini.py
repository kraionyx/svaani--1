"""Gemini on Vertex AI — the selected Medical Understanding provider.

Uses Vertex **controlled generation** (``response_mime_type='application/json'`` +
``response_schema``) so the model's output validates against our Pydantic schemas.
``temperature=0`` keeps structuring deterministic — we organize what was said, we
never "create".

Requires ``google-genai`` and a Vertex project. Designed for the Mumbai region
(``asia-south1``) to keep PHI in-country (DPDPA). Import is deferred so the rest of
the app runs without the SDK installed.
"""
from __future__ import annotations

from typing import Iterator, TypeVar

from pydantic import BaseModel

from app.config import Settings

T = TypeVar("T", bound=BaseModel)


class VertexGeminiLLM:
    # Models that rejected our ``thinking_budget`` with a 400 (process-wide, keyed by
    # model id). ``thinking_budget=0`` disables thinking on Flash/Flash-Lite, but
    # gemini-2.5-pro and the 3.x models reject 0 outright ("does not support setting
    # thinking_budget to 0"). The first such failure records the model here so every
    # later call (any instance) drops ``thinking_config`` and lets the model use its
    # default — no hardcoded model list, works across providers/versions.
    _thinking_unsupported: set[str] = set()

    def __init__(self, settings: Settings) -> None:
        from google import genai  # deferred import
        from google.genai import types

        self._types = types
        self.settings = settings
        if settings.vertex_api_key:
            # Express-mode API key. Note: regional residency is not pinned the same way
            # as project+location — use the project path below for strict DPDPA residency.
            self.client = genai.Client(vertexai=True, api_key=settings.vertex_api_key)
        else:
            # ADC / service-account creds; project + regional endpoint pin residency.
            self.client = genai.Client(
                vertexai=True,
                project=settings.vertex_project,
                location=settings.vertex_location,
            )

    @property
    def available(self) -> bool:
        return True

    def _thinking_config(self):
        """Cap/disable Gemini "thinking" to cut latency on deterministic structuring.

        ``thinking_budget=0`` turns thinking off on Flash/Flash-Lite. Returns ``None``
        if the installed SDK predates ThinkingConfig, or if this model has already
        rejected our budget (see ``_thinking_unsupported``) — in which case we omit the
        kwarg and let the model think with its default budget.
        """
        thinking_cls = getattr(self._types, "ThinkingConfig", None)
        if thinking_cls is None or self.settings.gemini_model in self._thinking_unsupported:
            return None
        return thinking_cls(thinking_budget=self.settings.llm_thinking_budget)

    @staticmethod
    def _is_thinking_error(exc: Exception) -> bool:
        return "thinking_budget" in str(exc).lower()

    def _generate(self, prompt: str, *, system: str | None, schema: type[BaseModel] | None):
        """``generate_content`` with one self-healing retry: if the model rejects our
        ``thinking_budget`` (400), record it and retry without ``thinking_config``."""
        try:
            return self.client.models.generate_content(
                model=self.settings.gemini_model, contents=prompt,
                config=self._config(system=system, schema=schema),
            )
        except Exception as exc:  # noqa: BLE001 — only the thinking_budget 400 is retried
            if self._is_thinking_error(exc) and self.settings.gemini_model not in self._thinking_unsupported:
                VertexGeminiLLM._thinking_unsupported.add(self.settings.gemini_model)
                return self.client.models.generate_content(
                    model=self.settings.gemini_model, contents=prompt,
                    config=self._config(system=system, schema=schema),
                )
            raise

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

    def generate_structured(self, prompt: str, schema: type[T], *, system: str | None = None) -> T:
        resp = self._generate(prompt, system=system, schema=schema)
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        return schema.model_validate_json(resp.text)

    def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        return self._generate(prompt, system=system, schema=None).text or ""

    def generate_text_stream(self, prompt: str, *, system: str | None = None) -> Iterator[str]:
        """Stream the model's text output chunk-by-chunk (server-side streaming).

        Self-heals the ``thinking_budget`` 400 the same way as ``_generate``: the
        rejection surfaces at request submission (before any chunk), so retrying once
        without ``thinking_config`` is safe.
        """
        def _open() -> Iterator[str]:
            stream = self.client.models.generate_content_stream(
                model=self.settings.gemini_model,
                contents=prompt,
                config=self._config(system=system, schema=None),
            )
            for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    yield text

        try:
            yield from _open()
        except Exception as exc:  # noqa: BLE001 — only the thinking_budget 400 is retried
            if self._is_thinking_error(exc) and self.settings.gemini_model not in self._thinking_unsupported:
                VertexGeminiLLM._thinking_unsupported.add(self.settings.gemini_model)
                yield from _open()
            else:
                raise
