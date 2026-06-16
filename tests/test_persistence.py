"""Goal 2 fix — operational data survives a restart (durable repository).

Exercises the SQLite-backed PersistentRepository: write a few entities, then build a FRESH
repository over the SAME store (a simulated restart) and confirm everything hydrated back.
The Supabase backend shares this exact logic, differing only in the DB driver.
"""
from __future__ import annotations

from app.config import get_settings
from app.data.repo_sql import _SqliteStore, build_persistent_repository
from app.schemas.review import ConsultationReview, ReviewRating


def _repo(path):
    return build_persistent_repository(_SqliteStore(str(path)), get_settings())


def test_entities_survive_restart(tmp_path):
    db = tmp_path / "op.db"
    repo = _repo(db)

    # Seeded prompts/model are written through on first boot.
    assert repo.active_prompt("extract") is not None

    repo.add_review(ConsultationReview(
        id="rev-1", session_id="sess-1", rating=ReviewRating.NEEDS_IMPROVEMENT,
        error_categories=[], comment="son not mother",
    ))
    repo.set_flag("beta", True, {"pct": 10})
    repo.add_edit("sess-1", {"section_id": "assessment", "before": "A", "after": "B",
                             "applied": True, "instruction": "tidy"})

    # Simulated restart: brand-new repository instance over the same file.
    repo2 = _repo(db)
    assert "rev-1" in repo2.reviews
    # needs_improvement auto-enqueued an admin review, which must have persisted too.
    assert any(ar.review_id == "rev-1" for ar in repo2.admin_reviews.values())
    flags = {f["key"]: f for f in repo2.list_flags()}
    assert flags["beta"]["enabled"] is True and flags["beta"]["value"] == {"pct": 10}
    edits = repo2.list_edits("sess-1")
    assert len(edits) == 1 and edits[0]["after"] == "B"
    # The seed only runs once — a restart must NOT duplicate prompt versions.
    assert len(repo2.list_prompts(name="extract")) == len(repo.list_prompts(name="extract"))


def test_prompt_activation_persists(tmp_path):
    db = tmp_path / "op.db"
    repo = _repo(db)
    from app.schemas.review import PromptVersion

    repo.add_prompt_version(PromptVersion(id="pv-x", name="extract", version=2,
                                          content="v2", active=True))
    repo2 = _repo(db)
    actives = [p for p in repo2.list_prompts(name="extract") if p.active]
    assert len(actives) == 1 and actives[0].version == 2


def test_undo_redo_flags_round_trip(tmp_path):
    repo = _repo(tmp_path / "o.db")
    repo.add_edit("s", {"section_id": "a", "before": "0", "after": "1", "applied": True})
    repo.set_edit_undone("s", 1, True)
    assert repo.list_edits("s")[0]["undone"] is True
    repo.set_edit_undone("s", 1, False)
    assert repo.list_edits("s")[0]["undone"] is False
    # A new edit clears the redo branch.
    repo.set_edit_undone("s", 1, True)
    repo.add_edit("s", {"section_id": "a", "before": "1", "after": "2", "applied": True})
    repo.drop_undone_edits("s")
    seqs = [e["seq"] for e in repo.list_edits("s")]
    assert 1 not in seqs  # the undone edit was dropped
