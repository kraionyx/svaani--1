"""Serves the ACTIVE prompt version to the pipeline (Goal 10 — make versioning real).

Before this, every stage imported its instruction constant directly from
``app.pipeline.prompts``, so activating a version in the admin console changed nothing.
Stages now call ``get_prompt(name)`` which returns the active ``PromptVersion.content``
from the operational repo, falling back to the hardcoded constant when no version is active
(keyless dev, tests, or a name with no row yet).

The active set is loaded once and cached in-process (no per-request DB read on the hot path,
Goal 12); ``invalidate_prompts()`` clears the cache and is called by the activate/create
routes so a newly-activated prompt takes effect immediately.
"""
from __future__ import annotations

import logging
import threading

from app.pipeline import prompts as _const

logger = logging.getLogger("svaani.prompts")

#: Versioned prompt name -> fallback constant. These names match the seed in
#: ``app.data.repo._seed`` and ``_CATEGORY_TO_PROMPT``.
_FALLBACK: dict[str, str] = {
    "clean": _const.CLEAN_INSTRUCTION,
    "extract": _const.EXTRACT_INSTRUCTION,
    "risk": _const.RISK_INSTRUCTION,
    "relationship": _const.RELATIONSHIP_INSTRUCTION,
}


class PromptProvider:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: dict[str, str] = {}
        self._override: dict[str, str] = {}  # eval/A-B: serve a candidate without deploying
        self._loaded = False

    def _ensure(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                from app.data.repo import get_repo  # lazy: repo seeds from prompts.py

                repo = get_repo()
                for name in _FALLBACK:
                    pv = repo.active_prompt(name)
                    if pv and pv.content:
                        self._cache[name] = pv.content
            except Exception:  # noqa: BLE001 — never block a note on prompt loading
                logger.warning("could not load active prompts; using constants", exc_info=True)
            self._loaded = True

    def get(self, name: str) -> str:
        self._ensure()
        with self._lock:
            if name in self._override:
                return self._override[name]
            if name in self._cache:
                return self._cache[name]
        return _FALLBACK.get(name, "")

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()
            self._loaded = False

    def set_override(self, mapping: dict[str, str] | None) -> None:
        with self._lock:
            self._override = dict(mapping or {})

    def clear_override(self) -> None:
        with self._lock:
            self._override = {}


_provider: PromptProvider | None = None


def get_prompt_provider() -> PromptProvider:
    global _provider
    if _provider is None:
        _provider = PromptProvider()
    return _provider


def get_prompt(name: str) -> str:
    """Active content for a versioned prompt name, or its hardcoded fallback."""
    return get_prompt_provider().get(name)


def invalidate_prompts() -> None:
    """Drop the cache so a newly activated prompt version is picked up immediately."""
    get_prompt_provider().invalidate()
