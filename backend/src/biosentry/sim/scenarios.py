"""The twelve scripted patients behind data/synthetic (PLAN CP3).

Every patient, name and number here is synthetic (I6). A scenario is a script, not a
result: it states how each vital moves over the last six hours, what the nurse entered, which
labs exist and where the signal drops. NEWS2, rank, reasons and trend are never written here;
the generator's output goes through `news2()` and the arbiter, and the tests assert the
scripted `expected_news2`.

Tier B and Tier C content is demo (PLAN D11): scripted text and numbers, flagged
`synthetic`, never read by the arbiter.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from biosentry.schemas import Acvpu, FindingDirection, ProvenanceSource, Spo2Scale

Vital = Literal["heart_rate", "respiratory_rate", "spo2", "temperature"]
DEVICE_VITALS: tuple[Vital, ...] = ("heart_rate", "respiratory_rate", "spo2", "temperature")
Trajectory = Literal["deteriorating", "stable", "improving"]


@dataclass(frozen=True, slots=True)
class VitalPlan:
    start: float  # level six hours before as_of
    end: float  # the latest valid reading; the generator pins it exactly
    noise: float  # standard deviation of the slow wander around the path


@dataclass(frozen=True, slots=True)
class BinGap:
    """15-minute bins (0..23; bin 23 ends at as_of) with no usable signal."""

    bins: tuple[int, ...]
    vitals: tuple[Vital, ...] = DEVICE_VITALS


@dataclass(frozen=True, slots=True)
class NurseEntry:
    minutes_ago: int
    systolic: int | None  # None = not recorded
    diastolic: int | None
    acvpu: Acvpu
    on_oxygen: bool
    spo2_scale: Spo2Scale


@dataclass(frozen=True, slots=True)
class LabSpec:
    hours_old: float
    values: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class FindingSpec:
    id: str
    label: str
    value: str
    direction: FindingDirection | None
    source: ProvenanceSource
    significant: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class TierCSpec:
    risk_probability: float
    scored_seconds_ago: int
    attributions: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class NoteSpec:
    id: str
    author: str
    role: str
    minutes_ago: int
    content: str


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    name: str
    age: int
    sex: Literal["M", "F"]
    bed: str
    admitting_context: str
    story: str
    trajectory: Trajectory
    nurse: NurseEntry
    expected_news2: int | None  # None: the patient is expected to be NOT RANKED
    plans: Mapping[Vital, VitalPlan] | None = None  # None: no patch applied
    labs: LabSpec | None = None
    gaps: tuple[BinGap, ...] = ()
    signal_lost_min: int = 0  # the patch stopped sending this long before as_of
    irregular_hr: bool = False
    rr_baseline: float | None = None
    tier_b: tuple[FindingSpec, ...] = ()
    tier_c: TierCSpec | None = None
    notes: tuple[NoteSpec, ...] = ()


A = ProvenanceSource
D = FindingDirection


def _f(
    fid: str,
    label: str,
    value: str,
    direction: FindingDirection | None,
    source: ProvenanceSource,
    significant: bool,
    detail: str | None = None,
) -> FindingSpec:
    return FindingSpec(fid, label, value, direction, source, significant, detail)


def _plans(
    hr: tuple[float, float],
    rr: tuple[float, float],
    spo2: tuple[float, float],
    temp: tuple[float, float],
    hr_noise: float = 2.5,
) -> dict[Vital, VitalPlan]:
    return {
        "heart_rate": VitalPlan(hr[0], hr[1], hr_noise),
        "respiratory_rate": VitalPlan(rr[0], rr[1], 1.0),
        "spo2": VitalPlan(spo2[0], spo2[1], 0.6),
        "temperature": VitalPlan(temp[0], temp[1], 0.08),
    }


RANKED: tuple[Scenario, ...] = (
    Scenario(
        id="p-001",
        name="Santos, Maria",
        age=67,
        sex="F",
        bed="4A",
        admitting_context="Acute decompensated heart failure, admitted 36h ago",
        story="ADHF, worsening over the shift",
        trajectory="deteriorating",
        plans=_plans((102, 118), (20, 23), (96, 93), (37.0, 37.2), hr_noise=3.0),
        nurse=NurseEntry(20, 88, 52, Acvpu.A, False, Spo2Scale.scale_1),
        labs=LabSpec(
            1,
            {
                "bnp": 1840,
                "sodium": 133,
                "potassium": 3.8,
                "creatinine": 1.4,
                "bun": 28,
                "hemoglobin": 118,
                "wbc": 11.2,
                "platelet_count": 198000,
                "sgpt": 42,
                "blood_glucose": 126,
            },
        ),
        expected_news2=9,
        rr_baseline=16,
        tier_b=(
            _f(
                "af",
                "Arrhythmia burden",
                "12%",
                D.rising,
                A.device,
                True,
                "AF episodes over 6h window",
            ),
            _f("rr", "Respiratory rate", "", D.rising, A.device, True),
            _f(
                "pi",
                "Perfusion index",
                "0.30",
                D.falling,
                A.device,
                True,
                "trend declining over 3h",
            ),
            _f("hrv", "HRV (SDNN)", "28 ms", D.falling, A.device, True, "reduced variability"),
            _f("trop", "Troponin trend", "not measured", None, A.lab, False),
            _f(
                "k-mg",
                "K⁺",
                "3.8 mEq/L",
                D.stable,
                A.lab,
                False,
                "within range; no arrhythmia substrate",
            ),
            _f(
                "kdigo",
                "KDIGO stage",
                "Stage 1",
                D.rising,
                A.lab,
                True,
                "creatinine 1.4 mg/dL, rising",
            ),
            _f("lactate", "Lactate", "not measured", None, A.lab, False),
        ),
        tier_c=TierCSpec(
            0.23,
            420,
            (
                ("Respiratory rate vs baseline", 0.31),
                ("BNP (last lab)", 0.18),
                ("Pulse pressure narrowing", 0.14),
                ("SpO₂ trend slope (3h)", 0.09),
                ("Heart rate trend slope (3h)", 0.05),
                ("Diuretic response (6h)", -0.06),
            ),
        ),
        notes=(
            NoteSpec(
                "n-001",
                "RN Dela Cruz",
                "RN",
                15,
                "Patient restless, diaphoretic. BP trending down from previous shift. "
                "Elevated troponin noted -- MD notified.",
            ),
            NoteSpec(
                "n-002",
                "Dr Reyes",
                "MD",
                30,
                "Reviewed labs. Troponin rise consistent with NSTEMI. Cardiology consult "
                "placed. Hold metoprolol if SBP < 100.",
            ),
        ),
    ),
    Scenario(
        id="p-002",
        name="Reyes, Carlos",
        age=54,
        sex="M",
        bed="2B",
        admitting_context="Post-ACS step-down, 6h since transfer from CCU, on metoprolol",
        story="Post-ACS on oxygen, heart rate controlled by beta-blocker",
        trajectory="stable",
        plans=_plans((60, 58), (20, 22), (91, 93), (36.8, 36.8), hr_noise=1.5),
        nurse=NurseEntry(35, 104, 68, Acvpu.A, True, Spo2Scale.scale_1),
        labs=LabSpec(
            3,
            {
                "troponin": 0.42,
                "ck_mb": 38,
                "sodium": 139,
                "potassium": 4.1,
                "creatinine": 1.0,
                "bun": 16,
                "hemoglobin": 148,
                "wbc": 8.4,
                "platelet_count": 220000,
                "inr": 1.0,
                "blood_glucose": 98,
            },
        ),
        expected_news2=7,
        rr_baseline=18,
        tier_b=(
            _f("af", "Arrhythmia burden", "4%", D.stable, A.device, False),
            _f("rr", "Respiratory rate", "", D.rising, A.device, True),
            _f("pi", "Perfusion index", "0.60", D.stable, A.device, False),
            _f("hrv", "HRV (SDNN)", "42 ms", D.stable, A.device, False),
            _f(
                "trop",
                "Troponin trend",
                "0.42 ng/mL",
                D.new,
                A.lab,
                True,
                "single draw — repeat pending for trend",
            ),
            _f("k-mg", "K⁺", "4.1 mEq/L", D.stable, A.lab, False),
            _f("kdigo", "KDIGO stage", "No AKI", None, A.lab, False, "creatinine 1.0 mg/dL"),
            _f("lactate", "Lactate", "not measured", None, A.lab, False),
        ),
        tier_c=TierCSpec(
            0.12,
            300,
            (
                ("Troponin (last lab)", 0.16),
                ("Beta-blocker on board", -0.14),
                ("Age", 0.05),
                ("Heart rate variability (SDNN)", 0.04),
                ("Respiratory rate vs baseline", 0.03),
                ("SpO₂ trend slope (3h)", -0.02),
            ),
        ),
        notes=(
            NoteSpec(
                "n-003",
                "RN Santos",
                "RN",
                45,
                "Increased work of breathing. Repositioned to high Fowler's. SpO2 improved "
                "from 91% to 93% on 4L NC.",
            ),
        ),
    ),
    Scenario(
        id="p-003",
        name="Villanueva, Jose",
        age=45,
        sex="M",
        bed="1C",
        admitting_context="Post-operative day 1, CABG, stable",
        story="POD1 CABG, improving, low-grade fever settling",
        trajectory="improving",
        plans=_plans((108, 96), (18, 18), (95, 94), (38.6, 38.2)),
        nurse=NurseEntry(40, 100, 62, Acvpu.A, False, Spo2Scale.scale_1),
        labs=LabSpec(
            4,
            {
                "sodium": 140,
                "potassium": 4.3,
                "creatinine": 0.9,
                "bun": 14,
                "hemoglobin": 102,
                "hematocrit": 0.31,
                "wbc": 9.8,
                "platelet_count": 245000,
                "pt": 12.1,
                "inr": 1.1,
                "blood_glucose": 110,
            },
        ),
        expected_news2=5,
        rr_baseline=17,
        tier_b=(
            _f("af", "Arrhythmia burden", "1%", D.stable, A.device, False),
            _f("rr", "Respiratory rate", "", D.stable, A.device, False),
            _f("pi", "Perfusion index", "0.70", D.stable, A.device, False),
            _f("hrv", "HRV (RMSSD)", "35 ms", D.stable, A.device, False),
            _f(
                "trop",
                "Troponin trend",
                "not measured",
                None,
                A.lab,
                False,
                "expected post-op — order if chest pain",
            ),
            _f("k-mg", "K⁺", "4.3 mEq/L", D.stable, A.lab, False),
            _f("kdigo", "KDIGO stage", "No AKI", None, A.lab, False, "creatinine 0.9 mg/dL"),
            _f("lactate", "Lactate", "not measured", None, A.lab, False),
        ),
        tier_c=TierCSpec(
            0.08,
            540,
            (
                ("Post-op day 1", 0.11),
                ("Hemoglobin (last lab)", 0.07),
                ("Temperature trend (6h)", -0.05),
                ("Heart rate trend slope (3h)", -0.04),
                ("Respiratory rate vs baseline", 0.02),
            ),
        ),
        notes=(
            NoteSpec(
                "n-004",
                "RN Dela Cruz",
                "RN",
                70,
                "Patient alert and oriented. Tolerating oral meds. No acute complaints this shift.",
            ),
        ),
    ),
    Scenario(
        id="p-006",
        name="Bautista, Elena",
        age=72,
        sex="F",
        bed="3A",
        admitting_context="Heart failure with reduced EF, chronic, admitted for volume overload",
        story="HFrEF volume overload; patch repositioned four hours ago",
        trajectory="stable",
        plans=_plans((93, 94), (21, 22), (94, 94), (36.9, 36.9), hr_noise=2.0),
        nurse=NurseEntry(50, 110, 70, Acvpu.A, False, Spo2Scale.scale_1),
        labs=LabSpec(
            9,
            {
                "bnp": 920,
                "sodium": 131,
                "potassium": 4.6,
                "creatinine": 1.8,
                "bun": 32,
                "hemoglobin": 110,
                "wbc": 7.6,
                "platelet_count": 175000,
                "sgpt": 38,
                "blood_glucose": 118,
            },
        ),
        expected_news2=5,
        rr_baseline=18,
        gaps=(BinGap((8, 9, 10)),),  # 45 minutes without signal around T-4h
        tier_b=(
            _f("af", "Arrhythmia burden", "8%", D.rising, A.device, True),
            _f("rr", "Respiratory rate", "", D.stable, A.device, False),
            _f("pi", "Perfusion index", "0.45", D.falling, A.device, True, "below 0.50 threshold"),
            _f("hrv", "HRV (SDNN)", "31 ms", D.falling, A.device, True),
            _f("trop", "Troponin trend", "not measured", None, A.lab, False),
            _f(
                "k-mg",
                "K⁺ / Mg²⁺",
                "4.6 / -- mEq/L",
                D.rising,
                A.lab,
                False,
                "K⁺ high-normal; Mg not measured; watch against arrhythmia burden",
            ),
            _f(
                "kdigo",
                "KDIGO stage",
                "Stage 2",
                D.rising,
                A.lab,
                True,
                "creatinine 1.8 mg/dL, rising — labs 9h old",
            ),
            _f(
                "lactate",
                "Lactate",
                "not measured",
                None,
                A.lab,
                False,
                "would corroborate perfusion finding",
            ),
        ),
        tier_c=TierCSpec(
            0.14,
            660,
            (
                ("Creatinine trend", 0.13),
                ("BNP (last lab)", 0.10),
                ("Sodium (last lab)", 0.08),
                ("Perfusion index", 0.06),
                ("Respiratory rate vs baseline", 0.04),
                ("Labs stale (>8h)", 0.03),
            ),
        ),
    ),
    Scenario(
        id="p-007",
        name="Garcia, Roberto",
        age=61,
        sex="M",
        bed="5B",
        admitting_context="Heart failure, suspected, no echocardiogram yet",
        story="Suspected HF, workup incomplete, BNP not sent",
        trajectory="stable",
        plans=_plans((100, 100), (22, 22), (94, 94), (36.8, 36.8)),
        nurse=NurseEntry(55, 132, 84, Acvpu.A, False, Spo2Scale.scale_1),
        labs=LabSpec(
            5,
            {
                "sodium": 138,
                "potassium": 4.0,
                "creatinine": 1.1,
                "bun": 18,
                "hemoglobin": 142,
                "wbc": 6.8,
                "platelet_count": 230000,
                "blood_glucose": 105,
            },
        ),
        expected_news2=4,
        tier_b=(
            _f("af", "Arrhythmia burden", "2%", D.stable, A.device, False),
            _f(
                "rr",
                "Respiratory rate",
                "baseline pending",
                None,
                A.device,
                False,
                "insufficient wear time for personal baseline",
            ),
            _f("pi", "Perfusion index", "0.60", D.stable, A.device, False),
            _f("hrv", "HRV (SDNN)", "48 ms", D.stable, A.device, False),
            _f("trop", "Troponin trend", "not measured", None, A.lab, False),
            _f("k-mg", "K⁺", "4.0 mEq/L", D.stable, A.lab, False),
            _f("kdigo", "KDIGO stage", "No AKI", None, A.lab, False, "creatinine 1.1 mg/dL"),
            _f("lactate", "Lactate", "not measured", None, A.lab, False),
        ),
        tier_c=TierCSpec(
            0.09,
            480,
            (
                ("Incomplete workup (no echo)", 0.08),
                ("Blood pressure", 0.05),
                ("Heart rate trend slope (3h)", 0.04),
                ("Respiratory rate vs baseline", 0.03),
                ("Age", 0.03),
            ),
        ),
    ),
    Scenario(
        id="p-008",
        name="Mendoza, Ana",
        age=55,
        sex="F",
        bed="6A",
        admitting_context="Hypertensive urgency, responding to IV labetalol",
        story="Hypertensive urgency; rate falling on IV labetalol, SBP still above 220",
        trajectory="improving",
        plans=_plans((70, 52), (16, 16), (98, 98), (36.7, 36.7)),
        nurse=NurseEntry(25, 224, 118, Acvpu.A, False, Spo2Scale.scale_1),
        labs=LabSpec(
            2,
            {
                "sodium": 142,
                "potassium": 3.9,
                "creatinine": 0.9,
                "bun": 12,
                "hemoglobin": 132,
                "wbc": 7.2,
                "platelet_count": 260000,
                "sgpt": 28,
                "blood_glucose": 92,
            },
        ),
        expected_news2=3,
        rr_baseline=16,
        tier_b=(
            _f("af", "Arrhythmia burden", "1%", D.stable, A.device, False),
            _f("rr", "Respiratory rate", "", D.stable, A.device, False),
            _f("pi", "Perfusion index", "0.80", D.stable, A.device, False),
            _f("hrv", "HRV (SDNN)", "52 ms", D.stable, A.device, False),
            _f("trop", "Troponin trend", "not measured", None, A.lab, False),
            _f("k-mg", "K⁺", "3.9 mEq/L", D.stable, A.lab, False),
            _f("kdigo", "KDIGO stage", "No AKI", None, A.lab, False, "creatinine 0.9 mg/dL"),
            _f("lactate", "Lactate", "not measured", None, A.lab, False),
        ),
        tier_c=TierCSpec(
            0.05,
            360,
            (
                ("Systolic blood pressure", 0.07),
                ("Labetalol response", -0.06),
                ("Heart rate trend slope (3h)", -0.03),
                ("SpO₂ (current)", -0.02),
                ("Age", 0.02),
            ),
        ),
    ),
    Scenario(
        id="p-009",
        name="Cruz, Patricia",
        age=38,
        sex="F",
        bed="7B",
        admitting_context="Atrial fibrillation, rate controlled, awaiting cardioversion",
        story="Rate-controlled AF, irregular rhythm, heart rate easing",
        trajectory="improving",
        plans=_plans((108, 96), (16, 16), (95, 94), (36.6, 36.6), hr_noise=3.5),
        nurse=NurseEntry(45, 122, 76, Acvpu.A, False, Spo2Scale.scale_1),
        labs=LabSpec(
            6,
            {
                "sodium": 140,
                "potassium": 4.2,
                "creatinine": 0.8,
                "bun": 15,
                "hemoglobin": 128,
                "wbc": 6.0,
                "platelet_count": 210000,
                "blood_glucose": 88,
            },
        ),
        expected_news2=2,
        irregular_hr=True,
        rr_baseline=15,
        tier_b=(
            _f(
                "af",
                "Arrhythmia burden",
                "35%",
                D.falling,
                A.device,
                True,
                "AF burden declining with rate control",
            ),
            _f("rr", "Respiratory rate", "", D.stable, A.device, False),
            _f("pi", "Perfusion index", "0.70", D.stable, A.device, False),
            _f("hrv", "HRV (RMSSD)", "22 ms", D.stable, A.device, True, "reduced — expected in AF"),
            _f("trop", "Troponin trend", "not measured", None, A.lab, False),
            _f("k-mg", "K⁺", "4.2 mEq/L", D.stable, A.lab, False),
            _f("kdigo", "KDIGO stage", "No AKI", None, A.lab, False, "creatinine 0.8 mg/dL"),
            _f("lactate", "Lactate", "not measured", None, A.lab, False),
        ),
        tier_c=TierCSpec(
            0.06,
            600,
            (
                ("Arrhythmia burden", 0.09),
                ("Rate control (6h)", -0.05),
                ("Age", -0.03),
                ("Respiratory rate vs baseline", -0.02),
                ("SpO₂ trend slope (3h)", -0.02),
            ),
        ),
    ),
    Scenario(
        id="p-010",
        name="Aquino, Daniel",
        age=29,
        sex="M",
        bed="8A",
        admitting_context="Chest pain, low risk, admitted 4h ago for observation",
        story="Low-risk chest pain under observation; one respiratory-rate bin dropped",
        trajectory="stable",
        plans=_plans((98, 98), (14, 14), (99, 99), (36.5, 36.5)),
        nurse=NurseEntry(30, 110, 70, Acvpu.A, False, Spo2Scale.scale_1),
        labs=LabSpec(
            2,
            {
                "troponin": 0.009,
                "sodium": 141,
                "potassium": 4.0,
                "creatinine": 0.9,
                "bun": 13,
                "hemoglobin": 155,
                "wbc": 7.0,
                "platelet_count": 280000,
                "blood_glucose": 94,
            },
        ),
        expected_news2=2,
        gaps=(BinGap((20,), vitals=("respiratory_rate",)),),
        tier_b=(
            _f("af", "Arrhythmia burden", "0%", D.stable, A.device, False),
            _f(
                "rr",
                "Respiratory rate",
                "baseline pending",
                None,
                A.device,
                False,
                "insufficient wear time for personal baseline",
            ),
            _f("pi", "Perfusion index", "0.90", D.stable, A.device, False),
            _f("hrv", "HRV (SDNN)", "68 ms", D.stable, A.device, False),
            _f(
                "trop",
                "Troponin trend",
                "<0.01 ng/mL",
                D.stable,
                A.lab,
                False,
                "negative — reassuring",
            ),
            _f("k-mg", "K⁺", "4.0 mEq/L", D.stable, A.lab, False),
            _f("kdigo", "KDIGO stage", "No AKI", None, A.lab, False, "creatinine 0.9 mg/dL"),
            _f("lactate", "Lactate", "not measured", None, A.lab, False),
        ),
        tier_c=TierCSpec(
            0.03,
            300,
            (
                ("Troponin negative (last lab)", -0.06),
                ("Age", -0.05),
                ("Heart rate trend slope (3h)", 0.02),
                ("Respiratory rate vs baseline", 0.01),
                ("SpO₂ (current)", -0.01),
            ),
        ),
    ),
    Scenario(
        id="p-011",
        name="Tan, Lucinda",
        age=68,
        sex="F",
        bed="9A",
        admitting_context="Chronic stable angina, medication adjustment",
        story="Chronic stable angina; the patch lost signal 20 minutes ago and the labs are stale",
        trajectory="stable",
        plans=_plans((71, 70), (15, 15), (97, 97), (36.4, 36.4), hr_noise=1.5),
        nurse=NurseEntry(60, 106, 68, Acvpu.A, False, Spo2Scale.scale_1),
        labs=LabSpec(
            36,
            {
                "sodium": 139,
                "potassium": 4.4,
                "creatinine": 1.0,
                "bun": 17,
                "hemoglobin": 126,
                "wbc": 6.5,
                "platelet_count": 195000,
                "blood_glucose": 100,
            },
        ),
        expected_news2=1,
        signal_lost_min=20,
        rr_baseline=15,
        tier_b=(
            _f("af", "Arrhythmia burden", "1%", D.stable, A.device, False),
            _f("rr", "Respiratory rate", "", D.stable, A.device, False),
            _f("pi", "Perfusion index", "0.85", D.stable, A.device, False),
            _f("hrv", "HRV (SDNN)", "55 ms", D.stable, A.device, False),
            _f("trop", "Troponin trend", "not measured", None, A.lab, False),
            _f("k-mg", "K⁺", "4.4 mEq/L", D.stable, A.lab, False),
            _f("kdigo", "KDIGO stage", "No AKI", None, A.lab, False, "creatinine 1.0 mg/dL"),
            _f("lactate", "Lactate", "not measured", None, A.lab, False),
        ),
        tier_c=TierCSpec(
            0.04,
            4200,
            (
                ("Age", 0.05),
                ("Chronic angina history", 0.04),
                ("Heart rate trend slope (3h)", -0.02),
                ("Respiratory rate vs baseline", 0.01),
                ("SpO₂ trend slope (3h)", -0.01),
            ),
        ),
    ),
    Scenario(
        id="p-012",
        name="Lim, Francis",
        age=42,
        sex="M",
        bed="10B",
        admitting_context="Pericarditis, improving, discharge planned tomorrow",
        story="Pericarditis, settling; every parameter scores zero",
        trajectory="improving",
        plans=_plans((72, 70), (15, 14), (99, 99), (36.7, 36.5)),
        nurse=NurseEntry(65, 118, 72, Acvpu.A, False, Spo2Scale.scale_1),
        labs=LabSpec(
            3,
            {
                "sodium": 140,
                "potassium": 4.1,
                "creatinine": 0.8,
                "bun": 11,
                "hemoglobin": 150,
                "wbc": 5.8,
                "platelet_count": 240000,
                "blood_glucose": 90,
            },
        ),
        expected_news2=0,
        rr_baseline=15,
        tier_b=(
            _f("af", "Arrhythmia burden", "0%", D.stable, A.device, False),
            _f("rr", "Respiratory rate", "", D.falling, A.device, False),
            _f("pi", "Perfusion index", "0.90", D.stable, A.device, False),
            _f("hrv", "HRV (SDNN)", "62 ms", D.rising, A.device, False, "improving"),
            _f("trop", "Troponin trend", "not measured", None, A.lab, False),
            _f("k-mg", "K⁺", "4.1 mEq/L", D.stable, A.lab, False),
            _f("kdigo", "KDIGO stage", "No AKI", None, A.lab, False, "creatinine 0.8 mg/dL"),
            _f("lactate", "Lactate", "not measured", None, A.lab, False),
        ),
        tier_c=TierCSpec(
            0.02,
            5400,
            (
                ("Improving trajectory (24h)", -0.07),
                ("Age", -0.04),
                ("Heart rate trend slope (3h)", -0.03),
                ("Temperature trend (6h)", -0.02),
                ("Respiratory rate vs baseline", -0.01),
            ),
        ),
    ),
)

# NOT RANKED by design: one for each way a required input can be missing.
ABSTAINED: tuple[Scenario, ...] = (
    Scenario(  # patch on, device series present, no blood pressure recorded
        id="p-004",
        name="Flores, Ramon",
        age=73,
        sex="M",
        bed="4B",
        admitting_context="Heart failure with preserved EF, admitted 2h ago",
        story="Admitted two hours ago, patch on, blood pressure not yet recorded",
        trajectory="stable",
        plans=_plans((88, 88), (18, 18), (96, 96), (36.8, 36.8)),
        nurse=NurseEntry(100, None, None, Acvpu.A, False, Spo2Scale.scale_1),
        expected_news2=None,
    ),
    Scenario(  # no patch applied: no device data at all
        id="p-005",
        name="de Leon, Isabel",
        age=58,
        sex="F",
        bed="3B",
        admitting_context="Congestive heart failure, diuretic titration",
        story="Patch not yet applied",
        trajectory="stable",
        nurse=NurseEntry(45, 118, 74, Acvpu.A, False, Spo2Scale.scale_1),
        expected_news2=None,
    ),
)

ALL: tuple[Scenario, ...] = tuple(sorted(RANKED + ABSTAINED, key=lambda s: s.id))
