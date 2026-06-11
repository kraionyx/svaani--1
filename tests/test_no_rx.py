"""The platform never authors prescriptions — enforced structurally."""
from __future__ import annotations

import importlib.util

from app.schemas.clinical import MedicationMention, Provenance
from app.schemas.template import ComponentType


def test_no_prescription_generation_module():
    # There is deliberately no pipeline stage that authors a prescription.
    assert importlib.util.find_spec("app.pipeline.prescription") is None


def test_no_prescription_component_in_catalog():
    assert "PRESCRIPTION" not in {c.value for c in ComponentType}


def test_discussed_medications_are_non_authoritative():
    med = MedicationMention(
        name="Amoxicillin", dose="500mg", frequency="BD",
        verbatim_text="take amoxicillin 500 twice a day",
        provenance=Provenance(span_ids=["seg-0001"]),
    )
    assert med.authoritative is False
    # frozen: cannot be flipped after construction either.
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        med.authoritative = True
