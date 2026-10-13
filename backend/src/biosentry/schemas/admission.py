"""Station admission form input and the extraction stubs.

Wire names stay camelCase (the form already sends them); Python attributes are snake_case.
Optional fields default to None and nothing else: omitted means not entered (I1).
PhilHealth PIN is sensitive personal information (RA 10173); it is never cached or logged.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import Field

from .base import Age, CamelContract, Contract, Flag, Fraction
from .clinical import PartialLabInput
from .common import Acvpu

PHILHEALTH_PIN = r"^\d{2}-\d{9}-\d$"  # 2-9-1
BLOOD_PRESSURE_TEXT = r"^\d{2,3}/\d{2,3}$"  # nurse-typed at the form; split once at admit

Positive = Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0)]


class Sex(StrEnum):
    M = "M"
    F = "F"


class AdmissionCondition(StrEnum):
    ambulatory = "ambulatory"
    wheelchair = "wheelchair"
    stretcher = "stretcher"


class AdmissionRoute(StrEnum):
    er_triage = "er_triage"
    direct_admission = "direct_admission"
    transfer = "transfer"


class CivilStatus(StrEnum):
    single = "single"
    married = "married"
    widowed = "widowed"
    separated = "separated"


class AdmitPatientInput(CamelContract):
    # Identity (DOH face sheet)
    last_name: str
    first_name: str
    middle_name: str | None = None
    name_extension: str | None = None  # Jr, Sr, III
    date_of_birth: date
    age: Age
    sex: Sex
    civil_status: CivilStatus | None = None
    contact_number: str | None = None
    philhealth_pin: Annotated[str, Field(pattern=PHILHEALTH_PIN)] | None = None
    # Admission details
    bed: str
    admission_route: AdmissionRoute
    condition_on_admission: AdmissionCondition | None = None
    chief_complaint: str
    admitting_context: str
    attending_physician: str
    allergies: str | None = None  # free text or "NKDA"
    # CV-specific
    weight_kg: Positive | None = None
    height_cm: Positive | None = None
    # Initial vitals (nurse-entered)
    initial_bp: Annotated[str, Field(pattern=BLOOD_PRESSURE_TEXT)] | None = None
    initial_avpu: Acvpu | None = None


class PartialAdmitPatientInput(CamelContract):
    """AdmitPatientInput with every field optional (extraction results)."""

    last_name: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    name_extension: str | None = None
    date_of_birth: date | None = None
    age: Age | None = None
    sex: Sex | None = None
    civil_status: CivilStatus | None = None
    contact_number: str | None = None
    philhealth_pin: Annotated[str, Field(pattern=PHILHEALTH_PIN)] | None = None
    bed: str | None = None
    admission_route: AdmissionRoute | None = None
    condition_on_admission: AdmissionCondition | None = None
    chief_complaint: str | None = None
    admitting_context: str | None = None
    attending_physician: str | None = None
    allergies: str | None = None
    weight_kg: Positive | None = None
    height_cm: Positive | None = None
    initial_bp: Annotated[str, Field(pattern=BLOOD_PRESSURE_TEXT)] | None = None
    initial_avpu: Acvpu | None = None


class LabExtractionResult(Contract):
    values: PartialLabInput
    confidence: dict[str, Fraction]
    synthetic: Flag
    model_id: str


class PatientExtractionResult(Contract):
    values: PartialAdmitPatientInput
    confidence: dict[str, Fraction]
    synthetic: Flag
    model_id: str
