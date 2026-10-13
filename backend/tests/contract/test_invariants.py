"""I1-I6 enforced by the schemas themselves (CP1 gate bars)."""

import re
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from samples import provenance, sample

from biosentry.schemas import (
    AbstainedRow,
    AcvpuMeasurement,
    BloodPressureMeasurement,
    ClinicalNote,
    FlagMeasurement,
    LabExtractionResult,
    NumberMeasurement,
    PatientExtractionResult,
    Provenance,
    ScoreRow,
    Spo2ScaleMeasurement,
    TierCInput,
)
from biosentry.schemas.openapi import build_openapi

MEASUREMENTS = [
    NumberMeasurement,
    FlagMeasurement,
    AcvpuMeasurement,
    Spo2ScaleMeasurement,
    BloodPressureMeasurement,
]
IDS = [m.__name__ for m in MEASUREMENTS]


# --- I1: missing is missing -------------------------------------------------------------


@pytest.mark.parametrize("model", MEASUREMENTS, ids=IDS)
def test_absent_needs_a_reason_and_carries_no_value(model: type[BaseModel]) -> None:
    payload = sample(model)
    payload["data"] = {"present": False}
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    payload["data"] = {"present": False, "reason": "not_measured", "value": 0}
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("model", MEASUREMENTS, ids=IDS)
def test_present_needs_a_value(model: type[BaseModel]) -> None:
    payload = sample(model)
    payload["data"] = {"present": True}
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    payload["data"] = {"present": True, "value": None}
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_blood_pressure_is_structured_and_positive() -> None:
    payload = sample(BloodPressureMeasurement)
    payload["data"]["value"] = "120/80"  # the display string is never accepted as a value
    with pytest.raises(ValidationError):
        BloodPressureMeasurement.model_validate(payload)
    payload["data"]["value"] = {"systolic": 0, "diastolic": 80}
    with pytest.raises(ValidationError):
        BloodPressureMeasurement.model_validate(payload)


@pytest.mark.parametrize("bad", ["X", "a", "", None, 1])
def test_acvpu_is_the_five_nhs_levels(bad: Any) -> None:
    payload = sample(AcvpuMeasurement)
    payload["data"]["value"] = bad
    with pytest.raises(ValidationError):
        AcvpuMeasurement.model_validate(payload)
    for level in "ACVPU":
        payload["data"]["value"] = level
        AcvpuMeasurement.model_validate(payload)


def test_spo2_scale_is_one_or_two() -> None:
    payload = sample(Spo2ScaleMeasurement)
    for bad in (0, 3, "1", True):
        payload["data"]["value"] = bad
        with pytest.raises(ValidationError):
            Spo2ScaleMeasurement.model_validate(payload)


# --- I2: every value carries provenance ----------------------------------------------------


@pytest.mark.parametrize("model", MEASUREMENTS, ids=IDS)
@pytest.mark.parametrize("key", ["source", "tier", "observed_at", "quality"])
def test_measurement_requires_provenance_fields(model: type[BaseModel], key: str) -> None:
    payload = sample(model)
    del payload["provenance"][key]
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("model", MEASUREMENTS, ids=IDS)
def test_measurement_requires_provenance_object(model: type[BaseModel]) -> None:
    payload = sample(model)
    del payload["provenance"]
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"observed_at": "2026-09-03T07:00:00"},  # naive timestamp is ambiguous
        {"source": "guess"},
        {"quality": "great"},
        {"tier": "D"},
        {"synthetic": "true"},
    ],
    ids=lambda o: next(iter(o)),
)
def test_provenance_rejects_malformed_values(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Provenance.model_validate(provenance(**overrides))


# --- I4: abstention is an output, not a score -----------------------------------------------


def test_abstained_row_requires_reason_and_instruction() -> None:
    for key in ("reason", "instruction"):
        payload = sample(AbstainedRow)
        del payload[key]
        with pytest.raises(ValidationError):
            AbstainedRow.model_validate(payload)


def test_abstained_row_has_no_score_or_rank() -> None:
    names = set(AbstainedRow.model_fields)
    assert not names & {"score", "rank", "trend", "sort_tier", "vitals", "tier_b", "tier_c"}
    for key in ("score", "rank"):
        payload = sample(AbstainedRow)
        payload[key] = 0
        with pytest.raises(ValidationError):
            AbstainedRow.model_validate(payload)


def test_a_ranked_row_cannot_be_built_without_a_score() -> None:
    payload = sample(ScoreRow)
    del payload["score"]
    with pytest.raises(ValidationError):
        ScoreRow.model_validate(payload)


# --- I6: synthetic flag propagates -----------------------------------------------------------

SYNTHETIC_RECORDS = [
    ScoreRow,
    AbstainedRow,
    ClinicalNote,
    Provenance,
    LabExtractionResult,
    PatientExtractionResult,
    TierCInput,
]


@pytest.mark.parametrize("model", SYNTHETIC_RECORDS, ids=lambda m: m.__name__)
def test_synthetic_is_required_and_boolean(model: type[BaseModel]) -> None:
    assert model.model_fields["synthetic"].is_required()
    payload = sample(model)
    del payload["synthetic"]
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    payload["synthetic"] = "true"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


# --- I3: Tier C reads features, never verdicts -------------------------------------------------

VERDICT_NAME = re.compile(
    r"score|rank|news2|verdict|finding|significan|escalat|arbiter|priority|abstain|"
    r"tier_a|tier_b|sort_tier|pathway|trigger",
    re.IGNORECASE,
)
VERDICT_MODELS = {
    "ScoreRow",
    "AbstainedRow",
    "TierAScore",
    "TierBreakdown",
    "TierBData",
    "TierBFinding",
    "TierCData",
    "TierStatus",
    "EscalationReason",
    "PatientDetail",
    "WardResponse",
}


def _reachable_schemas(root: str) -> dict[str, dict[str, Any]]:
    schemas = build_openapi()["components"]["schemas"]
    seen: dict[str, dict[str, Any]] = {}
    stack = [root]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen[name] = schemas[name]
        stack.extend(re.findall(r"#/components/schemas/(\w+)", str(schemas[name])))
    return seen


def test_tier_c_input_has_no_verdict_field_names() -> None:
    offenders = [
        f"{model}.{prop}"
        for model, schema in _reachable_schemas("TierCInput").items()
        for prop in schema.get("properties", {})
        if VERDICT_NAME.search(prop)
    ]
    assert offenders == []


def test_tier_c_input_cannot_reach_a_verdict_model() -> None:
    reachable = set(_reachable_schemas("TierCInput"))
    assert reachable.isdisjoint(VERDICT_MODELS), reachable & VERDICT_MODELS
