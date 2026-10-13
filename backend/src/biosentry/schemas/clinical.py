"""Vitals, vital series and the lab panel."""

from pydantic import Field

from .base import Contract, NonNegNum, Num
from .common import (
    AcvpuMeasurement,
    BloodPressureMeasurement,
    FlagMeasurement,
    NumberMeasurement,
    Spo2ScaleMeasurement,
)


class VitalHistory(Contract):
    # The fixture generator emits a chart label ("HH:MM"); CP3 decides the final form.
    time: str
    value: Num


class Vitals(Contract):
    heart_rate: NumberMeasurement
    respiratory_rate: NumberMeasurement
    spo2: NumberMeasurement
    temperature: NumberMeasurement
    blood_pressure: BloodPressureMeasurement
    consciousness: AcvpuMeasurement
    # NEWS2 inputs the original contract lacked (D3). Nurse-sourced, provenance required.
    supplemental_o2: FlagMeasurement
    spo2_scale: Spo2ScaleMeasurement


class VitalTrends(Contract):
    heart_rate: list[Num]
    respiratory_rate: list[Num]
    spo2: list[Num]
    temperature: list[Num]


class VitalHistoryFull(Contract):
    heart_rate: list[VitalHistory]
    respiratory_rate: list[VitalHistory]
    spo2: list[VitalHistory]


class LabPanel(Contract):
    """Units follow Philippine hospital convention. null = no result; never zero (I1)."""

    # Cardiac biomarkers
    troponin: NumberMeasurement | None = Field(description="ng/mL (conventional) or ng/L (hs)")
    ck_mb: NumberMeasurement | None = Field(description="U/L")
    bnp: NumberMeasurement | None = Field(description="pg/mL")
    nt_probnp: NumberMeasurement | None = Field(description="pg/mL")
    # Electrolytes
    sodium: NumberMeasurement | None = Field(description="mEq/L")
    potassium: NumberMeasurement | None = Field(description="mEq/L")
    chloride: NumberMeasurement | None = Field(description="mEq/L")
    magnesium: NumberMeasurement | None = Field(description="mg/dL")
    calcium: NumberMeasurement | None = Field(description="mg/dL")
    # Renal
    creatinine: NumberMeasurement | None = Field(description="mg/dL")
    bun: NumberMeasurement | None = Field(description="mg/dL")
    # Hematology
    hemoglobin: NumberMeasurement | None = Field(description="g/L (PH convention)")
    hematocrit: NumberMeasurement | None = Field(description="fraction (0-1)")
    wbc: NumberMeasurement | None = Field(description="x10^9/L")
    platelet_count: NumberMeasurement | None = Field(description="/mm^3")
    # Coagulation
    pt: NumberMeasurement | None = Field(description="seconds")
    inr: NumberMeasurement | None = Field(description="ratio")
    # Liver (PH naming)
    sgpt: NumberMeasurement | None = Field(description="U/L (ALT)")
    sgot: NumberMeasurement | None = Field(description="U/L (AST)")
    # Metabolic
    blood_glucose: NumberMeasurement | None = Field(description="mg/dL")
    lactate: NumberMeasurement | None = Field(description="mmol/L")
    # Meta
    freshness_hours: NonNegNum | None


class PartialLabInput(Contract):
    """Nurse- or OCR-entered lab values. Omitted = not entered; there is no default value."""

    troponin: Num | None = None
    ck_mb: Num | None = None
    bnp: Num | None = None
    nt_probnp: Num | None = None
    sodium: Num | None = None
    potassium: Num | None = None
    chloride: Num | None = None
    magnesium: Num | None = None
    calcium: Num | None = None
    creatinine: Num | None = None
    bun: Num | None = None
    hemoglobin: Num | None = None
    hematocrit: Num | None = None
    wbc: Num | None = None
    platelet_count: Num | None = None
    pt: Num | None = None
    inr: Num | None = None
    sgpt: Num | None = None
    sgot: Num | None = None
    blood_glucose: Num | None = None
    lactate: Num | None = None
