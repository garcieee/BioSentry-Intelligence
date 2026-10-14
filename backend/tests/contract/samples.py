"""One minimal valid JSON payload per contract model.

Every payload is plain JSON data (what crosses the wire). The tests mutate deep copies to
prove what the schemas reject.
"""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from biosentry.schemas import (
    CONTRACT_MODELS,
    AbstainedRow,
    AcvpuMeasurement,
    AdmitPatientInput,
    BloodPressure,
    BloodPressureMeasurement,
    ClinicalNote,
    EscalationReason,
    FlagMeasurement,
    LabExtractionResult,
    LabPanel,
    MeasurementAbsent,
    NewNote,
    NumberMeasurement,
    NurseVitalsInput,
    PartialAdmitPatientInput,
    PartialLabInput,
    PatientDetail,
    PatientExtractionResult,
    PatientSummary,
    Provenance,
    ScoreRow,
    Session,
    Spo2ScaleMeasurement,
    TierAScore,
    TierBData,
    TierBFinding,
    TierBreakdown,
    TierCAttribution,
    TierCData,
    TierCInput,
    TierStatus,
    UnscoredPatient,
    VitalHistory,
    VitalHistoryFull,
    Vitals,
    VitalsRecorded,
    VitalTrends,
    WardResponse,
)
from biosentry.schemas.common import (
    AcvpuPresent,
    BloodPressurePresent,
    FlagPresent,
    NumberPresent,
    Spo2ScalePresent,
)

NOW = "2026-09-03T07:00:00Z"

LAB_FIELDS = [
    "troponin",
    "ck_mb",
    "bnp",
    "nt_probnp",
    "sodium",
    "potassium",
    "chloride",
    "magnesium",
    "calcium",
    "creatinine",
    "bun",
    "hemoglobin",
    "hematocrit",
    "wbc",
    "platelet_count",
    "pt",
    "inr",
    "sgpt",
    "sgot",
    "blood_glucose",
    "lactate",
]


def provenance(**overrides: Any) -> dict[str, Any]:
    base = {
        "source": "device",
        "tier": None,
        "observed_at": NOW,
        "computed_at": None,
        "model_id": None,
        "synthetic": True,
        "quality": "ok",
    }
    return {**base, **overrides}


def present(value: Any) -> dict[str, Any]:
    return {"present": True, "value": value}


def absent(reason: str = "not_measured") -> dict[str, Any]:
    return {"present": False, "reason": reason}


def measurement(data: dict[str, Any]) -> dict[str, Any]:
    return {"data": data, "provenance": provenance()}


def vitals() -> dict[str, Any]:
    return {
        "heart_rate": measurement(present(118)),
        "respiratory_rate": measurement(present(26)),
        "spo2": measurement(present(91)),
        "temperature": measurement(present(37.2)),
        "blood_pressure": measurement(present({"systolic": 88, "diastolic": 52})),
        "consciousness": measurement(present("A")),
        "supplemental_o2": measurement(absent("not_recorded")),
        "spo2_scale": measurement(absent("not_recorded")),
    }


def vital_trends() -> dict[str, Any]:
    return {k: [1.0, None, 2.0] for k in ("heart_rate", "respiratory_rate", "spo2", "temperature")}


def labs() -> dict[str, Any]:
    panel: dict[str, Any] = dict.fromkeys(LAB_FIELDS)
    panel["bnp"] = measurement(present(1840))
    panel["freshness_hours"] = 1
    return panel


def tier_status() -> dict[str, Any]:
    return {"tier": "A", "live": True, "label": "NEWS2"}


def finding() -> dict[str, Any]:
    return {
        "id": "af",
        "label": "Arrhythmia burden",
        "value": "12%",
        "direction": "rising",
        "source": "device",
        "significant": True,
        "detail": "AF episodes over 6h window",
    }


def tier_c_data() -> dict[str, Any]:
    return {
        "risk_probability": 0.23,
        "forecast_window": "next 1-4h",
        "scored_seconds_ago": 420,
        "attributions": [{"feature": "Respiratory rate vs baseline", "contribution": 0.31}],
    }


def score_row() -> dict[str, Any]:
    return {
        "id": "p-001",
        "rank": 1,
        "score": 9,
        "trend": "rising",
        "name": "Santos, Maria",
        "age": 67,
        "sex": "F",
        "bed": "4A",
        "admitting_context": "Acute decompensated heart failure",
        "mechanism": "Sorted on NEWS2.",
        "supporting": "HR 118 bpm",
        "vitals": vitals(),
        "vital_trends": vital_trends(),
        "labs": labs(),
        "sort_tier": "A",
        "tier_status": [tier_status()],
        "tier_b": {"findings": [finding()]},
        "tier_c": tier_c_data(),
        "escalation_reasons": [{"rule": "tier_a_threshold", "text": "NEWS2 >= 7"}],
        "synthetic": True,
        "signal_quality": 94,
        "last_update_s": 4,
    }


def unscored() -> dict[str, Any]:
    row = score_row()
    keys = (
        "id", "name", "age", "sex", "bed", "admitting_context", "trend", "mechanism",
        "supporting", "vitals", "vital_trends", "labs", "tier_b", "tier_c", "signal_quality",
        "last_update_s", "synthetic",
    )  # fmt: skip
    state = {key: row[key] for key in keys}
    state["vital_history"] = {
        k: [{"time": "2026-09-03T06:30:00Z", "value": 97}]
        for k in ("heart_rate", "respiratory_rate", "spo2")
    }
    return state


def abstained_row() -> dict[str, Any]:
    return {
        "id": "p-011",
        "name": "Cruz, Ana",
        "age": 41,
        "sex": "F",
        "bed": "7C",
        "admitting_context": "Post-op day 1",
        "reason": "No patch applied",
        "instruction": "Apply patch and verify signal",
        "synthetic": True,
    }


def admit_input() -> dict[str, Any]:
    return {
        "lastName": "Santos",
        "firstName": "Maria",
        "dateOfBirth": "1958-04-02",
        "age": 67,
        "sex": "F",
        "bed": "4A",
        "admissionRoute": "er_triage",
        "chiefComplaint": "Dyspnea",
        "admittingContext": "Acute decompensated heart failure",
        "attendingPhysician": "Dr Reyes",
    }


_BUILDERS: dict[type[BaseModel], Any] = {
    Provenance: provenance,
    BloodPressure: lambda: {"systolic": 120, "diastolic": 80},
    MeasurementAbsent: absent,
    NumberPresent: lambda: present(118),
    NumberMeasurement: lambda: measurement(present(118)),
    FlagPresent: lambda: present(True),
    FlagMeasurement: lambda: measurement(present(True)),
    AcvpuPresent: lambda: present("A"),
    AcvpuMeasurement: lambda: measurement(present("A")),
    Spo2ScalePresent: lambda: present(1),
    Spo2ScaleMeasurement: lambda: measurement(present(1)),
    BloodPressurePresent: lambda: present({"systolic": 120, "diastolic": 80}),
    BloodPressureMeasurement: lambda: measurement(present({"systolic": 120, "diastolic": 80})),
    VitalHistory: lambda: {"time": "2026-09-03T06:30:00Z", "value": 97},
    Vitals: vitals,
    VitalTrends: vital_trends,
    VitalHistoryFull: lambda: {
        k: [{"time": "2026-09-03T06:30:00Z", "value": 97}]
        for k in ("heart_rate", "respiratory_rate", "spo2")
    },
    LabPanel: labs,
    PartialLabInput: lambda: {"troponin": 0.04},
    TierStatus: tier_status,
    TierBFinding: finding,
    TierBData: lambda: {"findings": [finding()]},
    TierCAttribution: lambda: {"feature": "BNP (last lab)", "contribution": -0.06},
    TierCData: tier_c_data,
    TierCInput: lambda: {
        "patient_id": "p-001",
        "as_of": NOW,
        "age": 67,
        "sex": "F",
        "admitting_context": "Acute decompensated heart failure",
        "vitals": vitals(),
        "vital_trends": vital_trends(),
        "labs": labs(),
        "synthetic": True,
    },
    EscalationReason: lambda: {
        "rule": "tier_b_finding",
        "text": "KDIGO rising",
        "pathway": "renal",
    },
    ScoreRow: score_row,
    AbstainedRow: abstained_row,
    WardResponse: lambda: {
        "ward": "4 East",
        "clinician": "RN Dela Cruz",
        "shift": "day",
        "receiving_data": True,
        "sort_tier": "A",
        "tier_status": [tier_status()],
        "ranked": [score_row()],
        "abstained": [abstained_row()],
    },
    TierAScore: lambda: {"score": 9, "label": "NEWS2 9"},
    TierBreakdown: lambda: {
        "tier_a": {"score": 9, "label": "NEWS2 9"},
        "tier_b": {"findings": [finding()]},
        "tier_c": tier_c_data(),
    },
    PatientDetail: lambda: {
        **score_row(),
        "vital_history": {
            k: [{"time": "2026-09-03T06:30:00Z", "value": 97}]
            for k in ("heart_rate", "respiratory_rate", "spo2")
        },
        "tier_breakdown": {
            "tier_a": {"score": 9, "label": "NEWS2 9"},
            "tier_b": None,
            "tier_c": None,
        },
    },
    ClinicalNote: lambda: {
        "id": "n-001",
        "patient_id": "p-001",
        "author": "RN Dela Cruz",
        "role": "RN",
        "timestamp": "2026-09-03T06:45:00Z",
        "content": "Patient restless.",
        "synthetic": True,
    },
    Session: lambda: {"clinician_id": "c-01", "ward": "4 East", "role": "rn"},
    NewNote: lambda: {"author": "RN Dela Cruz", "role": "RN", "content": "Patient restless."},
    PatientSummary: lambda: {"id": "p-001", "name": "Santos, Maria", "bed": "4A", "ranked": True},
    NurseVitalsInput: lambda: {"systolic": 120, "diastolic": 80},
    VitalsRecorded: lambda: {
        "patient_id": "p-004",
        "blood_pressure": measurement(present({"systolic": 120, "diastolic": 80})),
        "consciousness": None,
        "supplemental_o2": None,
        "spo2_scale": None,
        "ranked": True,
        "rank": 3,
        "score": 4,
        "not_ranked_reason": None,
        "not_ranked_instruction": None,
    },
    UnscoredPatient: lambda: unscored(),
    AdmitPatientInput: admit_input,
    PartialAdmitPatientInput: lambda: {"lastName": "Santos"},
    LabExtractionResult: lambda: {
        "values": {"troponin": 0.04},
        "confidence": {"troponin": 0.94},
        "synthetic": True,
        "model_id": "stub-ocr-0",
    },
    PatientExtractionResult: lambda: {
        "values": {"lastName": "Santos"},
        "confidence": {"lastName": 0.9},
        "synthetic": True,
        "model_id": "stub-ocr-0",
    },
}

assert set(_BUILDERS) == set(CONTRACT_MODELS), (
    "samples.py must define a valid payload for every contract model: "
    f"missing {[m.__name__ for m in set(CONTRACT_MODELS) - set(_BUILDERS)]}"
)


def sample(model: type[BaseModel]) -> dict[str, Any]:
    """A fresh valid payload for `model` (safe to mutate)."""
    return deepcopy(_BUILDERS[model]())
