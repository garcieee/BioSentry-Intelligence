"""NEWS2 (RCP 2017): band edges, aggregate rule, abstention, rounding, reasons (CP4 gate bar)."""

import itertools
import re
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from biosentry.domain.scoring.tier_a import (
    InputProblem,
    News2Abstained,
    News2Inputs,
    News2Score,
    ParameterScore,
    Problem,
    Risk,
    inputs_from_vitals,
    round_half_up,
    score_news2,
)
from biosentry.domain.scoring.tier_a import tables as t
from biosentry.schemas import Acvpu, Spo2Scale, Vitals
from samples import measurement, present, vitals

# Scores 0 on every parameter.
BASE = News2Inputs(
    respiratory_rate=16,
    spo2=98,
    spo2_scale=Spo2Scale.scale_1,
    supplemental_o2=False,
    systolic_bp=120,
    heart_rate=70,
    consciousness=Acvpu.A,
    temperature=37.0,
)


def score(**changes: Any) -> News2Score:
    result = score_news2(replace(BASE, **changes))
    assert isinstance(result, News2Score), result
    return result


def parameter(result: News2Score, name: str) -> ParameterScore:
    return next(p for p in result.parameters if p.parameter == name)


def test_base_case_scores_zero_everywhere() -> None:
    result = score()
    assert result.total == 0
    assert result.risk is Risk.low
    assert [p.parameter for p in result.parameters] == [
        "respiratory_rate",
        "spo2",
        "supplemental_o2",
        "systolic_bp",
        "heart_rate",
        "consciousness",
        "temperature",
    ]
    assert {p.score for p in result.parameters} == {0}


# --- Both edges of every band (RCP 2017 chart 1) ------------------------------------------

EDGES = [
    # respiratory rate
    ("respiratory_rate", 8, 3), ("respiratory_rate", 9, 1), ("respiratory_rate", 11, 1),
    ("respiratory_rate", 12, 0), ("respiratory_rate", 20, 0), ("respiratory_rate", 21, 2),
    ("respiratory_rate", 24, 2), ("respiratory_rate", 25, 3),
    # SpO2, scale 1 (BASE)
    ("spo2", 91, 3), ("spo2", 92, 2), ("spo2", 93, 2), ("spo2", 94, 1), ("spo2", 95, 1),
    ("spo2", 96, 0),
    # systolic BP
    ("systolic_bp", 90, 3), ("systolic_bp", 91, 2), ("systolic_bp", 100, 2),
    ("systolic_bp", 101, 1), ("systolic_bp", 110, 1), ("systolic_bp", 111, 0),
    ("systolic_bp", 219, 0), ("systolic_bp", 220, 3),
    # heart rate
    ("heart_rate", 40, 3), ("heart_rate", 41, 1), ("heart_rate", 50, 1), ("heart_rate", 51, 0),
    ("heart_rate", 90, 0), ("heart_rate", 91, 1), ("heart_rate", 110, 1), ("heart_rate", 111, 2),
    ("heart_rate", 130, 2), ("heart_rate", 131, 3),
    # temperature
    ("temperature", 35.0, 3), ("temperature", 35.1, 1), ("temperature", 36.0, 1),
    ("temperature", 36.1, 0), ("temperature", 38.0, 0), ("temperature", 38.1, 1),
    ("temperature", 39.0, 1), ("temperature", 39.1, 2),
]  # fmt: skip


@pytest.mark.parametrize(("field", "value", "expected"), EDGES)
def test_band_edges(field: str, value: float, expected: int) -> None:
    assert parameter(score(**{field: value}), field).score == expected


SCALE_2 = [  # (SpO2, on oxygen, expected SpO2 score)
    (83, False, 3), (84, False, 2), (85, False, 2), (86, False, 1), (87, False, 1),
    (88, False, 0), (92, False, 0), (93, False, 0), (97, False, 0), (100, False, 0),
    (83, True, 3), (84, True, 2), (85, True, 2), (86, True, 1), (87, True, 1),
    (88, True, 0), (92, True, 0), (93, True, 1), (94, True, 1), (95, True, 2),
    (96, True, 2), (97, True, 3), (100, True, 3),
]  # fmt: skip


@pytest.mark.parametrize(("spo2", "on_oxygen", "expected"), SCALE_2)
def test_spo2_scale_2_edges(spo2: float, on_oxygen: bool, expected: int) -> None:
    result = score(spo2=spo2, spo2_scale=Spo2Scale.scale_2, supplemental_o2=on_oxygen)
    assert parameter(result, "spo2").score == expected


def test_scale_changes_the_meaning_of_the_same_saturation() -> None:
    # 88-92 % is 3 / 2 / 2 / 3 on scale 1 but 0 on scale 2.
    assert parameter(score(spo2=90), "spo2").score == 3
    assert parameter(score(spo2=90, spo2_scale=Spo2Scale.scale_2), "spo2").score == 0


@pytest.mark.parametrize(("on_oxygen", "expected"), [(False, 0), (True, 2)])
def test_supplemental_oxygen(on_oxygen: bool, expected: int) -> None:
    assert parameter(score(supplemental_o2=on_oxygen), "supplemental_o2").score == expected


@pytest.mark.parametrize(
    ("level", "expected"),
    [(Acvpu.A, 0), (Acvpu.C, 3), (Acvpu.V, 3), (Acvpu.P, 3), (Acvpu.U, 3)],
)
def test_consciousness(level: Acvpu, expected: int) -> None:
    assert parameter(score(consciousness=level), "consciousness").score == expected


# --- An independent if-chain oracle over the whole range -----------------------------------


def oracle_rr(v: int) -> int:
    return 3 if v <= 8 else 1 if v <= 11 else 0 if v <= 20 else 2 if v <= 24 else 3


def oracle_hr(v: int) -> int:
    if v <= 40:
        return 3
    if v <= 50:
        return 1
    if v <= 90:
        return 0
    if v <= 110:
        return 1
    return 2 if v <= 130 else 3


def oracle_sbp(v: int) -> int:
    return 3 if v <= 90 else 2 if v <= 100 else 1 if v <= 110 else 0 if v <= 219 else 3


def oracle_spo2(v: int, scale: int, on_o2: bool) -> int:
    if scale == 1:
        return 3 if v <= 91 else 2 if v <= 93 else 1 if v <= 95 else 0
    if v <= 83:
        return 3
    if v <= 85:
        return 2
    if v <= 87:
        return 1
    if v <= 92 or not on_o2:
        return 0
    return 1 if v <= 94 else 2 if v <= 96 else 3


def oracle_temp(tenths: int) -> int:
    return (
        3
        if tenths <= 350
        else 1
        if tenths <= 360
        else 0
        if tenths <= 380
        else (1 if tenths <= 390 else 2)
    )


def test_integer_parameters_match_the_oracle_over_the_range() -> None:
    for v in range(301):  # 0 is a real reading for rate parameters (apnoea, asystole)
        assert parameter(score(respiratory_rate=v), "respiratory_rate").score == oracle_rr(v)
        assert parameter(score(heart_rate=v), "heart_rate").score == oracle_hr(v)
    for v in range(1, 301):  # 0 SBP and 0 SpO2 abstain (zero-fill), see the tests below
        assert parameter(score(systolic_bp=v), "systolic_bp").score == oracle_sbp(v)
    for v in range(1, 101):
        for scale in (Spo2Scale.scale_1, Spo2Scale.scale_2):
            for on_o2 in (False, True):
                got = parameter(
                    score(spo2=v, spo2_scale=scale, supplemental_o2=on_o2), "spo2"
                ).score
                assert got == oracle_spo2(v, int(scale), on_o2), (v, scale, on_o2)


def test_temperature_matches_the_oracle_on_every_tenth() -> None:
    for tenths in range(300, 431):
        got = parameter(score(temperature=tenths / 10), "temperature").score
        assert got == oracle_temp(tenths), tenths / 10


# --- Aggregate rule (chart 2) -------------------------------------------------------------


def oracle_risk(total: int, any_three: bool) -> Risk:
    if total >= 7:
        return Risk.high
    if total >= 5:
        return Risk.medium
    return Risk.low_medium if any_three else Risk.low


def test_aggregate_total_and_risk_over_many_combinations() -> None:
    grid: dict[str, list[Any]] = {
        "respiratory_rate": [8, 10, 16, 22, 26],
        "spo2": [90, 93, 95, 97],
        "supplemental_o2": [False, True],
        "systolic_bp": [85, 95, 105, 120, 225],
        "heart_rate": [35, 45, 70, 100, 120, 140],
        "consciousness": [Acvpu.A, Acvpu.U],
        "temperature": [34.5, 35.5, 37.0, 38.5, 39.5],
    }
    count = 0
    for combo in itertools.product(*grid.values()):
        values = dict(zip(grid, combo, strict=True))
        parts = [
            oracle_rr(int(values["respiratory_rate"])),
            oracle_spo2(int(values["spo2"]), 1, bool(values["supplemental_o2"])),
            2 if values["supplemental_o2"] else 0,
            oracle_sbp(int(values["systolic_bp"])),
            oracle_hr(int(values["heart_rate"])),
            0 if values["consciousness"] is Acvpu.A else 3,
            oracle_temp(round(float(values["temperature"]) * 10)),
        ]
        result = score(**values)
        assert result.total == sum(parts), values
        assert result.risk is oracle_risk(sum(parts), 3 in parts), values
        assert len(result.single_threes) == parts.count(3)
        count += 1
    assert count == 5 * 4 * 2 * 5 * 6 * 2 * 5


def test_worst_possible_observations_score_twenty() -> None:
    result = score(
        respiratory_rate=30,
        spo2=85,
        supplemental_o2=True,
        systolic_bp=80,
        heart_rate=150,
        consciousness=Acvpu.U,
        temperature=34.0,
    )
    assert result.total == 20
    assert result.risk is Risk.high


def test_a_single_three_in_a_low_total_is_low_medium() -> None:
    result = score(heart_rate=35)
    assert (result.total, result.risk) == (3, Risk.low_medium)
    assert result.single_threes == ("heart_rate",)


def test_a_single_three_still_listed_inside_a_high_total() -> None:
    result = score(heart_rate=35, respiratory_rate=26, systolic_bp=85)
    assert result.total == 9
    assert result.risk is Risk.high
    assert result.single_threes == ("respiratory_rate", "systolic_bp", "heart_rate")


@pytest.mark.parametrize(
    ("changes", "total", "risk"),
    [
        ({}, 0, Risk.low),
        ({"respiratory_rate": 10, "heart_rate": 45}, 2, Risk.low),
        ({"respiratory_rate": 22, "heart_rate": 120, "temperature": 38.5}, 5, Risk.medium),
        ({"respiratory_rate": 22, "heart_rate": 120, "temperature": 39.5}, 6, Risk.medium),
        (
            {"respiratory_rate": 22, "heart_rate": 120, "temperature": 39.5, "spo2": 94},
            7,
            Risk.high,
        ),
    ],
)
def test_total_bands(changes: dict[str, Any], total: int, risk: Risk) -> None:
    result = score(**changes)
    assert (result.total, result.risk) == (total, risk)


# --- Abstention: every input missing alone, never imputed ---------------------------------

REQUIRED = [
    "respiratory_rate",
    "spo2",
    "spo2_scale",
    "supplemental_o2",
    "systolic_bp",
    "heart_rate",
    "consciousness",
    "temperature",
]


@pytest.mark.parametrize("field", REQUIRED)
def test_each_input_missing_alone_abstains_naming_it(field: str) -> None:
    result = score_news2(replace(BASE, **{field: None}))
    assert isinstance(result, News2Abstained)
    assert result.problems == (InputProblem(field, Problem.missing),)
    assert not hasattr(result, "total")


def test_several_missing_inputs_are_all_named_in_chart_order() -> None:
    result = score_news2(replace(BASE, temperature=None, respiratory_rate=None, spo2_scale=None))
    assert isinstance(result, News2Abstained)
    assert [p.input for p in result.problems] == ["respiratory_rate", "spo2_scale", "temperature"]
    assert result.reason == (
        "NEWS2 not computed: respiratory rate missing, SpO2 scale missing, temperature missing"
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_missing_not_zero(bad: float) -> None:
    result = score_news2(replace(BASE, heart_rate=bad))
    assert isinstance(result, News2Abstained)
    assert result.problems == (InputProblem("heart_rate", Problem.missing),)


@pytest.mark.parametrize(
    ("field", "value"),
    [("heart_rate", -1), ("respiratory_rate", -0.5), ("spo2", 100.5), ("temperature", 1e30)],
)
def test_physically_impossible_numbers_abstain_and_never_clamp(field: str, value: float) -> None:
    changes: dict[str, Any] = {field: value}
    result = score_news2(replace(BASE, **changes))
    assert isinstance(result, News2Abstained)
    assert result.problems == (InputProblem(field, Problem.implausible),)


@pytest.mark.parametrize("field", ["respiratory_rate", "heart_rate"])
def test_zero_is_a_scorable_reading_for_apnoea_and_asystole(field: str) -> None:
    result = score(**{field: 0})  # real, if alarming, readings
    assert parameter(result, field).score == 3


@pytest.mark.parametrize("field", ["spo2", "temperature", "systolic_bp"])
def test_zero_is_a_zero_fill_for_spo2_temperature_and_sbp(field: str) -> None:
    changes: dict[str, Any] = {field: 0}
    result = score_news2(replace(BASE, **changes))
    assert isinstance(result, News2Abstained)
    assert result.problems == (InputProblem(field, Problem.implausible),)


# --- Rounding (PLAN D13): half-up, Decimal, not round() ---------------------------------

ROUNDING = [
    ("respiratory_rate", 8.49, "8", 3), ("respiratory_rate", 8.5, "9", 1),
    ("respiratory_rate", 11.5, "12", 0), ("respiratory_rate", 20.5, "21", 2),
    ("respiratory_rate", 24.5, "25", 3),
    ("heart_rate", 40.49, "40", 3), ("heart_rate", 40.5, "41", 1), ("heart_rate", 50.5, "51", 0),
    ("heart_rate", 90.5, "91", 1), ("heart_rate", 110.5, "111", 2), ("heart_rate", 130.5, "131", 3),
    ("spo2", 91.49, "91", 3), ("spo2", 91.5, "92", 2), ("spo2", 93.5, "94", 1),
    ("spo2", 95.5, "96", 0),
    ("systolic_bp", 90.5, "91", 2), ("systolic_bp", 100.5, "101", 1),
    ("systolic_bp", 110.5, "111", 0), ("systolic_bp", 219.5, "220", 3),
    ("temperature", 35.04, "35.0", 3), ("temperature", 35.05, "35.1", 1),
    ("temperature", 36.04, "36.0", 1), ("temperature", 36.05, "36.1", 0),
    ("temperature", 38.04, "38.0", 0), ("temperature", 38.05, "38.1", 1),
    ("temperature", 39.04, "39.0", 1), ("temperature", 39.05, "39.1", 2),
]  # fmt: skip


@pytest.mark.parametrize(("field", "raw", "rounded", "expected"), ROUNDING)
def test_half_up_rounding_before_banding(
    field: str, raw: float, rounded: str, expected: int
) -> None:
    row = parameter(score(**{field: raw}), field)
    assert (row.value, row.score) == (rounded, expected)


def test_rounding_is_not_pythons_bankers_rounding() -> None:
    assert round(8.5) == 8  # what round() would have done
    assert round_half_up(8.5, 0) == Decimal("9")
    assert round_half_up(0.5, 0) == Decimal("1")
    assert round_half_up(36.05, 1) == Decimal("36.1")  # 36.05 is 36.0499... as a binary float


# --- Show your work -----------------------------------------------------------------------


def test_reasons_cite_the_bands_that_fired() -> None:
    result = score(respiratory_rate=26, spo2=91, systolic_bp=88, heart_rate=118, temperature=37.2)
    assert result.total == 11
    assert result.reasons == (
        "Respiratory rate 26/min: ≥25 scores 3",
        "SpO2 91%: ≤91 scores 3",
        "Systolic BP 88 mmHg: ≤90 scores 3",
        "Heart rate 118/min: 111-130 scores 2",
        "Total 11 (≥7): high",
        "Single parameter at 3: respiratory rate, SpO2, systolic BP",
    )


def test_reasons_only_use_numbers_from_the_tables_and_the_inputs() -> None:
    allowed = {"0", "1", "2", "3", str(t.MEDIUM_FROM - 1), str(t.MEDIUM_FROM), str(t.HIGH_FROM)}
    for bands in (
        t.RESPIRATORY_RATE, t.SPO2_SCALE_1, t.SPO2_SCALE_2, t.SYSTOLIC_BP, t.HEART_RATE,
        t.TEMPERATURE,
    ):  # fmt: skip
        for band in bands:
            allowed |= set(re.findall(r"\d+(?:\.\d+)?", band.label))
    result = score(
        respiratory_rate=23, spo2=89, spo2_scale=Spo2Scale.scale_2, supplemental_o2=True,
        systolic_bp=95, heart_rate=105, consciousness=Acvpu.C, temperature=38.4,
    )  # fmt: skip
    allowed |= {p.value for p in result.parameters} | {str(result.total)}
    for reason in result.reasons:
        assert set(re.findall(r"\d+(?:\.\d+)?", reason)) <= allowed, reason


def test_no_fixture_style_threshold_phrases() -> None:
    for changes in ({}, {"heart_rate": 35}, {"respiratory_rate": 26, "heart_rate": 120}):
        for reason in score(**changes).reasons:
            assert not re.search(r"NEWS2\s*[≥=<>]", reason), reason


# --- Reading contract vitals --------------------------------------------------------------


def vitals_payload(**overrides: Any) -> dict[str, Any]:
    payload = vitals()
    payload["supplemental_o2"] = measurement(present(False))
    payload["spo2_scale"] = measurement(present(1))
    payload.update(overrides)
    return payload


def test_contract_vitals_are_scored_through_the_adapter() -> None:
    inputs = inputs_from_vitals(Vitals.model_validate(vitals_payload()))
    assert inputs == News2Inputs(26, 91, Spo2Scale.scale_1, False, 88, 118, Acvpu.A, 37.2)
    result = score_news2(inputs)
    assert isinstance(result, News2Score)
    assert (result.total, result.risk) == (11, Risk.high)


def test_absent_contract_measurements_abstain() -> None:
    payload = vitals()  # the CP1 sample leaves supplemental_o2 and spo2_scale absent
    result = score_news2(inputs_from_vitals(Vitals.model_validate(payload)))
    assert isinstance(result, News2Abstained)
    assert [p.input for p in result.problems] == ["spo2_scale", "supplemental_o2"]


def test_a_value_flagged_quality_missing_is_not_used() -> None:
    payload = vitals_payload()
    payload["heart_rate"]["provenance"]["quality"] = "missing"
    result = score_news2(inputs_from_vitals(Vitals.model_validate(payload)))
    assert isinstance(result, News2Abstained)
    assert result.problems == (InputProblem("heart_rate", Problem.missing),)


def test_degraded_quality_values_are_still_scored() -> None:
    payload = vitals_payload()
    payload["heart_rate"]["provenance"]["quality"] = "degraded"
    result = score_news2(inputs_from_vitals(Vitals.model_validate(payload)))
    assert isinstance(result, News2Score)
