"""Golden datasets for the eval harness (and the regression suite).

A dataset is a directory of JSON case files under ``app/eval/datasets/<name>/``. Each case
is a scripted, diarized transcript plus the expected relationship/attribution result — no
audio required, so it drives the same code path as ``POST /sessions/{id}/simulate``.

``build_raw`` deliberately seeds speaker roles by **first-seen order** (mimicking Sarvam's
diarization, the source of the multi-speaker bug) while preserving the raw ``diarized_label``,
so ``app.stt.doctor_detect`` and ``app.pipeline.subjects`` are exercised exactly as in prod.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.schemas.transcript import RawTranscript, SpeakerRole, TranscriptSegment

_DATASETS_DIR = Path(__file__).parent / "datasets"


class GoldenCase(BaseModel):
    id: str
    description: str = ""
    transcript: list[dict] = Field(default_factory=list)  # [{speaker, text, [confidence,start_ms,end_ms]}]
    expect: dict = Field(default_factory=dict)


def dataset_dir(name: str) -> Path:
    # Accept 'multispeaker@v1' as well as the on-disk 'multispeaker_v1'.
    return _DATASETS_DIR / name.replace("@", "_")


def load_dataset(name: str) -> list[GoldenCase]:
    d = dataset_dir(name)
    if not d.is_dir():
        raise FileNotFoundError(f"golden dataset not found: {d}")
    cases: list[GoldenCase] = []
    for path in sorted(d.glob("*.json")):
        cases.append(GoldenCase.model_validate_json(path.read_text(encoding="utf-8")))
    return cases


def build_raw(case: GoldenCase) -> RawTranscript:
    """Build a RawTranscript, seeding roles first-seen (doctor/patient/other) like Sarvam."""
    role_by_label: dict[str, SpeakerRole] = {}
    segments: list[TranscriptSegment] = []
    for i, row in enumerate(case.transcript):
        label = str(row["speaker"])
        if label not in role_by_label:
            order = len(role_by_label)
            role_by_label[label] = (
                SpeakerRole.DOCTOR if order == 0
                else SpeakerRole.PATIENT if order == 1
                else SpeakerRole.OTHER
            )
        segments.append(TranscriptSegment(
            id=f"seg-{i + 1:04d}",
            speaker=role_by_label[label],
            diarized_label=label,
            text=row.get("text", ""),
            confidence=float(row.get("confidence", 0.95)),
            start_ms=int(row.get("start_ms", i * 1000)),
            end_ms=int(row.get("end_ms", i * 1000 + 900)),
        ))
    return RawTranscript(session_id=case.id, segments=segments)
