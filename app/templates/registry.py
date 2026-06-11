"""Template registry — loads versioned templates and exposes the component catalog.

Templates live as JSON under ``docs/templates/`` (the drag-and-drop builder would
write here / to a DB). Each (template_id, version) is immutable; ``register`` adds a
new version rather than mutating an existing one.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.schemas.template import ComponentType, TemplateDefinition

#: project_root/docs/templates
_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "docs" / "templates"


class TemplateRegistry:
    def __init__(self) -> None:
        # keyed by (template_id, version)
        self._store: dict[tuple[str, int], TemplateDefinition] = {}

    # ── loading ────────────────────────────────────────────────────────────
    def load_dir(self, directory: Path | None = None) -> int:
        directory = directory or _DEFAULT_DIR
        count = 0
        if not directory.exists():
            return 0
        for path in sorted(directory.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.register(TemplateDefinition.model_validate(data))
            count += 1
        return count

    def register(self, template: TemplateDefinition) -> None:
        self._store[(template.template_id, template.version)] = template

    # ── lookup ───────────────────────────────────────────────────────────────
    def get(self, template_id: str, version: int | None = None) -> TemplateDefinition:
        if version is not None:
            return self._store[(template_id, version)]
        versions = [v for (tid, v) in self._store if tid == template_id]
        if not versions:
            raise KeyError(f"Unknown template '{template_id}'")
        return self._store[(template_id, max(versions))]

    def list_templates(self) -> list[TemplateDefinition]:
        return list(self._store.values())

    @staticmethod
    def component_catalog() -> list[dict[str, str]]:
        """The palette of components the drag-and-drop builder offers."""
        return [{"component": c.value, "label": c.value.replace("_", " ").title()} for c in ComponentType]


_registry: TemplateRegistry | None = None


def get_registry() -> TemplateRegistry:
    """Process-wide registry, lazily loaded from ``docs/templates/``."""
    global _registry
    if _registry is None:
        _registry = TemplateRegistry()
        _registry.load_dir()
    return _registry
