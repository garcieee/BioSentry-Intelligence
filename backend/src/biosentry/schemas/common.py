"""Provenance and measurement primitives (I1 missing is missing, I2 provenance on every value)."""

from enum import IntEnum, StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator

from .base import Contract, Flag, Num


class ProvenanceSource(StrEnum):
    device = "device"
    nurse = "nurse"
    lab = "lab"
    derived = "derived"
    model = "model"
    reference = "reference"


class Tier(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class QualityLevel(StrEnum):
    ok = "ok"
    degraded = "degraded"
    missing = "missing"


class Trend(StrEnum):
    rising = "rising"
    falling = "falling"
    stable = "stable"
    insufficient = "insufficient"


class Acvpu(StrEnum):
    """NEWS2 level of consciousness: Alert, new Confusion, Voice, Pain, Unresponsive."""

    A = "A"
    C = "C"
    V = "V"
    P = "P"
    U = "U"


class Spo2Scale(IntEnum):
    """RCP NEWS2 SpO2 scoring scale. Scale 2 is clinician-assigned (hypercapnic failure)."""

    scale_1 = 1
    scale_2 = 2


class Provenance(Contract):
    """Where a value came from. Every key is required; null is allowed only where stated."""

    source: ProvenanceSource
    tier: Tier | None
    observed_at: AwareDatetime
    computed_at: AwareDatetime | None
    model_id: str | None
    synthetic: Flag
    quality: QualityLevel


class BloodPressure(Contract):
    """Structured on purpose: the "SBP/DBP" string is display only and is never parsed."""

    systolic: Annotated[int, Field(strict=True, gt=0)]
    diastolic: Annotated[int, Field(strict=True, gt=0)]


class MeasurementAbsent(Contract):
    """A value that is not there, with the reason. Never a zero, never a default (I1)."""

    present: Literal[False]
    reason: str


# One Present/Measurement pair per value type. Explicit classes (not Generic[T]) so every
# value is strictly typed and the schema names stay stable in the generated TS.


class NumberPresent(Contract):
    present: Literal[True]
    value: Num


class NumberMeasurement(Contract):
    data: Annotated[NumberPresent | MeasurementAbsent, Field(discriminator="present")]
    provenance: Provenance


class FlagPresent(Contract):
    present: Literal[True]
    value: Flag


class FlagMeasurement(Contract):
    data: Annotated[FlagPresent | MeasurementAbsent, Field(discriminator="present")]
    provenance: Provenance


class AcvpuPresent(Contract):
    present: Literal[True]
    value: Acvpu


class AcvpuMeasurement(Contract):
    data: Annotated[AcvpuPresent | MeasurementAbsent, Field(discriminator="present")]
    provenance: Provenance


class Spo2ScalePresent(Contract):
    present: Literal[True]
    value: Spo2Scale

    @field_validator("value", mode="before")
    @classmethod
    def _integer_only(cls, value: object) -> object:
        # IntEnum would otherwise accept "1" and True.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("SpO2 scale must be the integer 1 or 2")
        return value


class Spo2ScaleMeasurement(Contract):
    data: Annotated[Spo2ScalePresent | MeasurementAbsent, Field(discriminator="present")]
    provenance: Provenance


class BloodPressurePresent(Contract):
    present: Literal[True]
    value: BloodPressure


class BloodPressureMeasurement(Contract):
    data: Annotated[BloodPressurePresent | MeasurementAbsent, Field(discriminator="present")]
    provenance: Provenance

