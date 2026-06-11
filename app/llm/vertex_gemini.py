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

from typing import TypeVar

from pydantic import BaseModel

from app.config import Settings

T = TypeVar("T", bound=BaseModel)


class VertexGeminiLLM:
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

    def _config(self, *, system: str | None, schema: type[BaseModel] | None):
        return self._types.GenerateContentConfig(
            temperature=self.settings.llm_temperature,
            max_output_tokens=self.settings.llm_max_output_tokens,
            system_instruction=system,
            response_mime_type="application/json" if schema else None,
            response_schema=schema,
        )

    def generate_structured(self, prompt: str, schema: type[T], *, system: str | None = None) -> T:
        resp = self.client.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=self._config(system=system, schema=schema),
        )
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        return schema.model_validate_json(resp.text)

    def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        resp = self.client.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=self._config(system=system, schema=None),
        )
        return resp.text or ""
