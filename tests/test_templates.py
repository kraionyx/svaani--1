"""Template loading + the ENT render round-trip from the brief's example."""
from __future__ import annotations

from app.schemas.template import ComponentType
from app.templates.renderer import render_note
from tests.conftest import section_by_id


def test_all_example_templates_load(registry):
    ids = {t.template_id for t in registry.list_templates()}
    assert {"soap", "ent", "ortho", "freeform"} <= ids


def test_ent_render_maps_regional_examination(registry, ent_extraction):
    template = registry.get("ent")
    note = render_note(ent_extraction, template)

    throat = section_by_id(note, "throat")
    nose = section_by_id(note, "nose")
    ear = section_by_id(note, "ear")

    assert throat.content_data == {"granular_ppw": True, "tonsillar_hypertrophy": "Grade 2"}
    assert nose.content_data == {"dns": "Left"}
    assert ear.empty is True  # ear was not discussed

    # Chief complaints rendered, in template order.
    cc = section_by_id(note, "chief_complaints")
    assert cc.component is ComponentType.CHIEF_COMPLAINTS
    assert "Throat Pain" in cc.content_text
    assert "Difficulty Swallowing" in cc.content_text


def test_custom_section_requires_schema_hint():
    import pytest
    from app.schemas.template import TemplateDefinition, TemplateSection

    with pytest.raises(ValueError):
        TemplateDefinition(
            template_id="bad", name="Bad",
            sections=[TemplateSection(id="x", component=ComponentType.CUSTOM, label="X")],
        )
