"""Clinical notes and the signed-in session."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .base import Contract, Flag
from .common import (
    Acvpu,
    AcvpuMeasurement,
    BloodPressureMeasurement,
    FlagMeasurement,
    Spo2Scale,
    Spo2ScaleMeasurement,
)


class ClinicalNote(Contract):
    id: str
    patient_id: str
    author: str
    role: str
    timestamp: AwareDatetime
    content: str
    synthetic: Flag  # I6: every seed/fixture record carries the flag


class SessionRole(StrEnum):
    rn = "rn"
    md = "md"
    charge_rn = "charge_rn"


class Session(Contract):
    clinician_id: str
    ward: str
    role: SessionRole


class NewNote(Contract):
    """The body of POST /patients/{id}/notes. The server assigns id, time and the flag."""

    author: str
    role: str
    content: str


class NurseVitalsInput(Contract):
    """Nurse-entered NEWS2 inputs (POST /patients/{id}/vitals): any subset, at least one.

    Blood pressure is a pair. Omitted means not entered (the stored value is left alone);
    there is no default and nothing is clamped: an impossible value is rejected.
    """

    systolic: Annotated[int, Field(strict=True)] | None = None
    diastolic: Annotated[int, Field(strict=True)] | None = None
    acvpu: Acvpu | None = None
    on_oxygen: Flag | None = None
    spo2_scale: Spo2Scale | None = None

    @field_validator("spo2_scale", mode="before")
    @classmethod
    def _integer_scale(cls, value: object) -> object:
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError("SpO2 scale must be the integer 1 or 2")
        return value

    @model_validator(mode="after")
    def _shape(self) -> Self:
        entered = (self.systolic, self.diastolic, self.acvpu, self.on_oxygen, self.spo2_scale)
        if all(v is None for v in entered):
            raise ValueError("record at least one value")
        if (self.systolic is None) != (self.diastolic is None):
            raise ValueError("systolic and diastolic are recorded together")
        return self


class VitalsRecorded(Contract):
    """What was stored (the echo, with provenance) and where the patient stands now."""

    patient_id: str
    blood_pressure: BloodPressureMeasurement | None
    consciousness: AcvpuMeasurement | None
    supplemental_o2: FlagMeasurement | None
    spo2_scale: Spo2ScaleMeasurement | None
    ranked: Flag
    rank: Annotated[int, Field(strict=True, ge=1)] | None
    score: Annotated[int, Field(strict=True, ge=0, le=20)] | None
    not_ranked_reason: str | None
    not_ranked_instruction: str | None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.ranked:
            if self.rank is None or self.score is None:
                raise ValueError("a ranked patient has a rank and a score")
            if self.not_ranked_reason is not None or self.not_ranked_instruction is not None:
                raise ValueError("a ranked patient has no NOT RANKED reason")
        else:
            if self.rank is not None or self.score is not None:
                raise ValueError("a NOT RANKED patient has no rank and no score (I4)")
            if self.not_ranked_reason is None or self.not_ranked_instruction is None:
                raise ValueError("a NOT RANKED patient names its reason and instruction")
        return self
