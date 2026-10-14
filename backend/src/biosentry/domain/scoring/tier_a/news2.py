"""Tier A: the National Early Warning Score 2 (RCP 2017), deterministic and pure.

Contract with callers:
  - Every input is required. A missing, non-finite or physically impossible input yields
    `News2Abstained` naming it; nothing is imputed, defaulted or clamped (I1, I4).
  - `spo2_scale` is an explicit recorded value and is never assumed (PLAN D12).
  - Inputs are rounded half-up before banding: integers for respiratory rate, SpO2, systolic
    BP and heart rate, one decimal for temperature (PLAN D13). Decimal, not `round()`.
  - The result shows its work: one `ParameterScore` per parameter, plus reason strings built
    only from `tables.py`.
"""

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Final

from biosentry.schemas import (
    Acvpu,
    AcvpuMeasurement,
    BloodPressureMeasurement,
    FlagMeasurement,
    NumberMeasurement,
    QualityLevel,
    Spo2Scale,
    Spo2ScaleMeasurement,
    Vitals,
)
from biosentry.schemas.common import (
    AcvpuPresent,
    BloodPressurePresent,
    FlagPresent,
    NumberPresent,
    Spo2ScalePresent,
)

from . import tables
from .tables import Band

# Guards against sensor garbage, not a clinical plausibility range (the quality gate owns that).
# Exactly 0 is a real reading for heart rate (asystole) and respiratory rate (apnoea), but for
# these three it is what a zero-fill looks like, so it abstains instead of scoring 3.
_PHYSICAL_MAX: Final = 1000.0
_SPO2_MAX: Final = 100.0
_ZERO_IS_NOT_A_READING: Final = frozenset({"spo2", "temperature", "systolic_bp"})


class Risk(StrEnum):
    low = "low"  # total 0-4 and no single parameter at 3
    low_medium = "low_medium"  # total 0-4 with a single parameter at 3 (urgent ward response)
    medium = "medium"  # total 5-6
    high = "high"  # total 7 or more


class Problem(StrEnum):
    missing = "missing"  # absent, quality "missing", or not a finite number
    implausible = (
        "implausible"  # impossible: negative, above 1000, SpO2 above 100, zero SpO2/temp/SBP
    )


@dataclass(frozen=True, slots=True)
class News2Inputs:
    respiratory_rate: float | None
    spo2: float | None
    spo2_scale: Spo2Scale | None
    supplemental_o2: bool | None
    systolic_bp: float | None
    heart_rate: float | None
    consciousness: Acvpu | None
    temperature: float | None


@dataclass(frozen=True, slots=True)
class InputProblem:
    input: str
    problem: Problem


@dataclass(frozen=True, slots=True)
class ParameterScore:
    parameter: str  # respiratory_rate, spo2, supplemental_o2, systolic_bp, ...
    value: str  # the rounded value as banded: "24", "36.6", "A", "oxygen"
    unit: str
    band: str  # label of the table row that matched, e.g. "21-24"
    score: int


@dataclass(frozen=True, slots=True)
class News2Score:
    total: int
    risk: Risk
    parameters: tuple[ParameterScore, ...]  # all seven, in chart order
    single_threes: tuple[str, ...]  # parameters scoring 3 (independent urgent trigger)
    spo2_scale: Spo2Scale
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class News2Abstained:
    problems: tuple[InputProblem, ...]

    @property
    def reason(self) -> str:
        return "NEWS2 not computed: " + ", ".join(
            f"{_LABELS[p.input]} {p.problem.value}" for p in self.problems
        )


News2Result = News2Score | News2Abstained

_LABELS: Final = {
    "respiratory_rate": "respiratory rate",
    "spo2": "SpO2",
    "spo2_scale": "SpO2 scale",
    "supplemental_o2": "supplemental oxygen",
    "systolic_bp": "systolic BP",
    "heart_rate": "heart rate",
    "consciousness": "level of consciousness",
    "temperature": "temperature",
}
_UNITS: Final = {
    "respiratory_rate": "/min",
    "spo2": "%",
    "supplemental_o2": "",
    "systolic_bp": " mmHg",
    "heart_rate": "/min",
    "consciousness": "",
    "temperature": " °C",
}


def round_half_up(value: float, places: int) -> Decimal:
    """Round the decimal as written (its repr) half-up: 36.05 -> 36.1, 8.5 -> 9."""
    return Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _band_for(bands: tuple[Band, ...], value: Decimal, on_oxygen: bool) -> Band:
    matches = [
        b
        for b in bands
        if (b.low is None or value >= b.low)
        and (b.high is None or value <= b.high)
        and (b.on_oxygen is None or b.on_oxygen == on_oxygen)
    ]
    if len(matches) != 1:  # the tables are a proven partition; this is unreachable
        raise AssertionError(f"{len(matches)} NEWS2 bands match {value}")
    return matches[0]


def _usable(name: str, value: float | None, problems: list[InputProblem]) -> float | None:
    """The value if it can be scored; otherwise record why not and return None."""
    if value is None or not math.isfinite(value):
        problems.append(InputProblem(name, Problem.missing))
        return None
    below_floor = value <= 0 if name in _ZERO_IS_NOT_A_READING else value < 0
    if below_floor or value > _PHYSICAL_MAX or (name == "spo2" and value > _SPO2_MAX):
        problems.append(InputProblem(name, Problem.implausible))
        return None
    return value


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]  # str.capitalize() would turn "SpO2" into "Spo2"


def _total_band(total: int) -> str:
    if total >= tables.HIGH_FROM:
        return f"≥{tables.HIGH_FROM}"
    if total >= tables.MEDIUM_FROM:
        return f"{tables.MEDIUM_FROM}-{tables.HIGH_FROM - 1}"
    return f"0-{tables.MEDIUM_FROM - 1}"


def score_news2(inputs: News2Inputs) -> News2Result:
    """Score one set of observations, or abstain naming exactly what blocks it."""
    problems: list[InputProblem] = []
    rr = _usable("respiratory_rate", inputs.respiratory_rate, problems)
    spo2 = _usable("spo2", inputs.spo2, problems)
    sbp = _usable("systolic_bp", inputs.systolic_bp, problems)
    hr = _usable("heart_rate", inputs.heart_rate, problems)
    temp = _usable("temperature", inputs.temperature, problems)
    scale, on_o2, level = inputs.spo2_scale, inputs.supplemental_o2, inputs.consciousness
    for name, recorded in (
        ("spo2_scale", scale),
        ("supplemental_o2", on_o2),
        ("consciousness", level),
    ):
        if recorded is None:
            problems.append(InputProblem(name, Problem.missing))
    if (
        rr is None or spo2 is None or sbp is None or hr is None or temp is None
        or scale is None or on_o2 is None or level is None
    ):  # fmt: skip
        by_name = {p.input: p for p in problems}
        return News2Abstained(tuple(by_name[n] for n in _LABELS if n in by_name))

    spo2_bands = tables.SPO2_SCALE_1 if scale == Spo2Scale.scale_1 else tables.SPO2_SCALE_2
    rows: list[ParameterScore] = []

    def banded(name: str, bands: tuple[Band, ...], raw: float, places: int) -> None:
        value = round_half_up(raw, places)
        band = _band_for(bands, value, on_o2)
        rows.append(ParameterScore(name, f"{value}", _UNITS[name], band.label, band.score))

    banded("respiratory_rate", tables.RESPIRATORY_RATE, rr, 0)
    banded("spo2", spo2_bands, spo2, 0)
    oxygen_label = tables.SUPPLEMENTAL_O2_LABEL[on_o2]
    rows.append(
        ParameterScore(
            "supplemental_o2", oxygen_label, "", oxygen_label, tables.SUPPLEMENTAL_O2_SCORE[on_o2]
        )
    )
    banded("systolic_bp", tables.SYSTOLIC_BP, sbp, 0)
    banded("heart_rate", tables.HEART_RATE, hr, 0)
    alert = level == Acvpu.A
    rows.append(
        ParameterScore(
            "consciousness",
            level.value,
            "",
            tables.CONSCIOUSNESS_ALERT_LABEL if alert else tables.CONSCIOUSNESS_OTHER_LABEL,
            tables.CONSCIOUSNESS_ALERT_SCORE if alert else tables.CONSCIOUSNESS_OTHER_SCORE,
        )
    )
    banded("temperature", tables.TEMPERATURE, temp, 1)

    total = sum(r.score for r in rows)
    single_threes = tuple(r.parameter for r in rows if r.score == tables.SINGLE_PARAMETER_TRIGGER)
    if total >= tables.HIGH_FROM:
        risk = Risk.high
    elif total >= tables.MEDIUM_FROM:
        risk = Risk.medium
    elif single_threes:
        risk = Risk.low_medium
    else:
        risk = Risk.low

    reasons = [
        f"{_sentence_case(_LABELS[r.parameter])} {r.value}{_UNITS[r.parameter]}: "
        f"{r.band} scores {r.score}"
        for r in rows
        if r.score > 0
    ]
    reasons.append(f"Total {total} ({_total_band(total)}): {risk.value.replace('_', '-')}")
    if single_threes:
        names = ", ".join(_LABELS[n] for n in single_threes)
        reasons.append(f"Single parameter at {tables.SINGLE_PARAMETER_TRIGGER}: {names}")

    return News2Score(
        total=total,
        risk=risk,
        parameters=tuple(rows),
        single_threes=single_threes,
        spo2_scale=scale,
        reasons=tuple(reasons),
    )


# --- Reading NEWS2 inputs off contract vitals ---------------------------------------------
# An absent measurement, or one whose provenance quality is "missing", becomes None and so
# abstains. Degraded values are used as recorded; the row's provenance already shows them.


def _number(m: NumberMeasurement) -> float | None:
    if m.provenance.quality is QualityLevel.missing or not isinstance(m.data, NumberPresent):
        return None
    return m.data.value


def _flag(m: FlagMeasurement) -> bool | None:
    if m.provenance.quality is QualityLevel.missing or not isinstance(m.data, FlagPresent):
        return None
    return m.data.value


def _scale(m: Spo2ScaleMeasurement) -> Spo2Scale | None:
    if m.provenance.quality is QualityLevel.missing or not isinstance(m.data, Spo2ScalePresent):
        return None
    return m.data.value


def _acvpu(m: AcvpuMeasurement) -> Acvpu | None:
    if m.provenance.quality is QualityLevel.missing or not isinstance(m.data, AcvpuPresent):
        return None
    return m.data.value


def _systolic(m: BloodPressureMeasurement) -> float | None:
    if m.provenance.quality is QualityLevel.missing or not isinstance(m.data, BloodPressurePresent):
        return None
    return float(m.data.value.systolic)


def inputs_from_vitals(vitals: Vitals) -> News2Inputs:
    return News2Inputs(
        respiratory_rate=_number(vitals.respiratory_rate),
        spo2=_number(vitals.spo2),
        spo2_scale=_scale(vitals.spo2_scale),
        supplemental_o2=_flag(vitals.supplemental_o2),
        systolic_bp=_systolic(vitals.blood_pressure),
        heart_rate=_number(vitals.heart_rate),
        consciousness=_acvpu(vitals.consciousness),
        temperature=_number(vitals.temperature),
    )
