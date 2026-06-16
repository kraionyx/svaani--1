"""Goal 10 — activating a prompt version actually changes what the pipeline uses.

Before the PromptProvider, stages imported prompt constants directly, so activation was
inert. These tests prove the connection: the active version flows to get_prompt(), and the
combined single-pass instruction is assembled from the active clean/extract/risk versions.
"""
from __future__ import annotations

from app.data.repo import get_repo
from app.pipeline.combined import _combined_instruction
from app.pipeline.prompt_provider import get_prompt, invalidate_prompts
from app.schemas.review import PromptVersion


def test_activation_changes_active_prompt():
    repo = get_repo()
    original = repo.active_prompt("extract")
    baseline = get_prompt("extract")
    assert baseline  # seeded from the constant
    try:
        repo.add_prompt_version(PromptVersion(
            id="pv-test-extract-xyz", name="extract", version=9999,
            content="CUSTOM_EXTRACT_SENTINEL", active=True,
        ))
        invalidate_prompts()
        assert get_prompt("extract") == "CUSTOM_EXTRACT_SENTINEL"
        # The single-pass path must inherit the activated extract text too.
        assert "CUSTOM_EXTRACT_SENTINEL" in _combined_instruction()
    finally:
        if original:
            repo.activate_prompt(original.id)
        invalidate_prompts()
    assert get_prompt("extract") == baseline  # state restored for other tests


def test_unknown_prompt_name_falls_back_empty():
    assert get_prompt("does-not-exist") == ""
