"""M4 leakage skeleton on the CP3b generator: the checks pass for the reference builder and
demonstrably fail for builders that leak, impute or smuggle in a verdict."""

import ast
import math
from collections.abc import Mapping
from pathlib import Path

import m4_leakage
import numpy as np
import pytest
from m4_leakage import (
    FORBIDDEN_NAME_PARTS,
    PERTURBATIONS,
    FeatureBuilder,
    Series,
    assert_feature_names_allowed,
    assert_gap_is_stale_not_fresh,
    assert_missing_stays_missing,
    assert_no_future_dependence,
    assert_no_verdict_features,
    assert_patient_level_split,
    reference_features,
)

from biosentry.sim.assemble import DEFAULT_SEED
from biosentry.sim.generator import MINUTES, simulate
from biosentry.sim.scenarios import RANKED

TIMES = (59, 179, 299, MINUTES - 1)


def _patients() -> list[tuple[str, dict[str, Series]]]:
    out: list[tuple[str, dict[str, Series]]] = []
    for index, scenario in enumerate(RANKED):
        signals = simulate(scenario, DEFAULT_SEED, index)
        assert signals is not None
        out.append((scenario.id, {str(v): x for v, x in signals.minutes.items()}))
    return out


PATIENTS = _patients()


# --- the reference builder passes ------------------------------------------------------


@pytest.mark.parametrize(("pid", "minutes"), PATIENTS, ids=[p for p, _ in PATIENTS])
def test_reference_builder_never_reads_the_future(pid: str, minutes: dict[str, Series]) -> None:
    for t in TIMES:
        assert_no_future_dependence(reference_features, minutes, t)


@pytest.mark.parametrize(("pid", "minutes"), PATIENTS, ids=[p for p, _ in PATIENTS])
def test_reference_builder_keeps_missing_missing(pid: str, minutes: dict[str, Series]) -> None:
    for t in TIMES:
        assert_missing_stays_missing(reference_features, minutes, t)


def test_reference_feature_names_carry_no_verdicts() -> None:
    names = reference_features(PATIENTS[0][1], MINUTES - 1)
    assert len(names) > 20
    assert_no_verdict_features(names)


def test_a_scripted_gap_shows_up_as_age_not_as_a_fresh_value() -> None:
    # wherever the generator has a vital with no usable minute for 15+ minutes up to t, the
    # features must say so: `age_min` >= 15 and `last` is the older reading, never NaN-filled
    checked = 0
    for _, minutes in PATIENTS:
        for vital, series in minutes.items():
            for t in range(120, MINUTES):
                tail = series[t - 14 : t + 1]
                if not np.isnan(tail).all() or np.isnan(series[: t - 14]).all():
                    continue
                feats = reference_features(minutes, t)
                age = feats[f"{vital}__age_min"]
                assert age >= 15
                assert feats[f"{vital}__last"] == series[t - int(age)]
                assert feats[f"{vital}__missing"] == 0.0  # it has history, it is just stale
                checked += 1
                break
    assert checked > 0, "the generator has no 15 minute gap: this check would be vacuous"


# --- the checks bite: leaky, imputing and verdict-carrying builders are caught ----------


def _leaky(minutes: Mapping[str, Series], t: int) -> dict[str, float]:
    feats = reference_features(minutes, t)
    for vital, series in minutes.items():  # whole-series statistic: reads the future
        feats[f"{vital}__mean_all"] = float(np.nanmean(series))
    return feats


def _imputing(minutes: Mapping[str, Series], t: int) -> dict[str, float]:
    return {k: (0.0 if math.isnan(v) else v) for k, v in reference_features(minutes, t).items()}


def test_a_builder_that_reads_the_future_is_caught() -> None:
    _, minutes = PATIENTS[0]
    with pytest.raises(AssertionError, match="depend on the future"):
        assert_no_future_dependence(_leaky, minutes, 179)


def test_a_builder_that_zero_fills_missing_values_is_caught() -> None:
    _, minutes = PATIENTS[0]
    with pytest.raises(AssertionError, match="that is a fill"):
        assert_missing_stays_missing(_imputing, minutes, 179)


@pytest.mark.parametrize(
    "name", ["news2_score", "tier_b_af_burden_flag", "kdigo_stage", "arbiter_priority", "label_24h"]
)
def test_verdict_and_outcome_named_features_are_caught(name: str) -> None:
    with pytest.raises(AssertionError, match="verdict or the outcome"):
        assert_no_verdict_features(["heart_rate__last", name])


def test_patients_may_not_straddle_the_split() -> None:
    assert_patient_level_split(["p-001", "p-002"], ["p-003"])
    with pytest.raises(AssertionError, match="both train and test"):
        assert_patient_level_split(["p-001", "p-002"], ["p-002", "p-003"])


# --- the labelling side: nothing in the M4 test support may use a verdict ------------------


def test_m4_support_does_not_import_scoring_code() -> None:
    path = Path(__file__).resolve().parents[1] / "support" / "m4_leakage.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not [m for m in modules if m.startswith("biosentry")], modules


def test_builders_are_plain_callables_over_series_and_time() -> None:
    builder: FeatureBuilder = reference_features
    out = builder({"heart_rate": np.array([80.0, np.nan, 82.0])}, 2)
    assert out["heart_rate__last"] == 82.0
    assert out["heart_rate__age_min"] == 0.0


# --- each future perturbation is necessary: a control only it can expose -------------------


def _ramp() -> dict[str, Series]:
    # a clean increasing series without gaps, so each control below is silent under the
    # other two perturbations by construction
    return {"heart_rate": np.linspace(60.0, 120.0, MINUTES)}


def _reads_order_only(minutes: Mapping[str, Series], t: int) -> dict[str, float]:
    future = minutes["heart_rate"][t + 1 :]  # 1.0 only when the future starts above its end
    return {"heart_rate__last": float(future[0] > future[-1])}


def _reads_finite_magnitude_only(minutes: Mapping[str, Series], t: int) -> dict[str, float]:
    future = minutes["heart_rate"][t + 1 :]  # counts implausible finite values
    return {"heart_rate__last": float(np.sum(future > 500.0))}


def _reads_missingness_only(minutes: Mapping[str, Series], t: int) -> dict[str, float]:
    future = minutes["heart_rate"][t + 1 :]  # notices that NaNs appeared
    return {"heart_rate__last": float(np.isnan(future).any())}


@pytest.mark.parametrize(
    ("builder", "only"),
    [
        (_reads_order_only, "reversed"),
        (_reads_finite_magnitude_only, "garbage"),
        (_reads_missingness_only, "nan"),
    ],
)
def test_each_perturbation_catches_a_leak_the_others_cannot(
    builder: FeatureBuilder, only: str
) -> None:
    minutes = _ramp()
    others = tuple(p for p in PERTURBATIONS if p != only)
    assert_no_future_dependence(builder, minutes, 179, perturbations=others)  # silent
    with pytest.raises(AssertionError, match=rf"depend on the future \({only}\)"):
        assert_no_future_dependence(builder, minutes, 179, perturbations=(only,))


# --- a mid-series gap is stale, never fresh (forward-fill is caught) -------------------------


def _forward_fill(series: Series) -> Series:
    idx = np.where(np.isnan(series), 0, np.arange(len(series)))
    return series[np.maximum.accumulate(idx)]


def _forward_filling(minutes: Mapping[str, Series], t: int) -> dict[str, float]:
    return reference_features({v: _forward_fill(s) for v, s in minutes.items()}, t)


def _gapped_case() -> tuple[dict[str, Series], int, int]:
    series = np.linspace(70.0, 110.0, MINUTES)
    gap_start, t = 200, 230
    series[gap_start : t + 15] = np.nan  # values before, a gap that covers t, values after
    return {"heart_rate": series}, t, gap_start


def test_reference_builder_reports_a_mid_series_gap_as_stale() -> None:
    minutes, t, gap_start = _gapped_case()
    assert_gap_is_stale_not_fresh(reference_features, minutes, t, "heart_rate", gap_start)
    feats = reference_features(minutes, t)
    assert feats["heart_rate__age_min"] == t - (gap_start - 1)
    assert feats["heart_rate__missing"] == 0.0
    assert feats["heart_rate__n_valid_60"] == 60 - (t - gap_start + 1)


def test_the_check_also_runs_on_a_gap_cut_into_a_generated_patient() -> None:
    _, minutes = PATIENTS[0]
    series = minutes["heart_rate"].copy()
    series[:240] = np.linspace(70.0, 90.0, 240)  # make the history gap-free first
    series[240:261] = np.nan
    assert_gap_is_stale_not_fresh(
        reference_features, {**minutes, "heart_rate": series}, 255, "heart_rate", 240
    )


def test_a_forward_filling_builder_is_caught() -> None:
    minutes, t, gap_start = _gapped_case()
    with pytest.raises(AssertionError, match=r"reads as current|not visible"):
        assert_gap_is_stale_not_fresh(_forward_filling, minutes, t, "heart_rate", gap_start)


def _claims_fresh(minutes: Mapping[str, Series], t: int) -> dict[str, float]:
    feats = reference_features(minutes, t)  # honest counts, but says the value is current
    feats["heart_rate__age_min"] = 0.0
    return feats


def _hides_the_gap_in_counts(minutes: Mapping[str, Series], t: int) -> dict[str, float]:
    feats = reference_features(minutes, t)  # honest age, but the window looks fully observed
    for w in (60, 180):
        feats[f"heart_rate__n_valid_{w}"] = float(w)
    return feats


def test_a_builder_that_understates_age_is_caught_by_the_age_requirement() -> None:
    minutes, t, gap_start = _gapped_case()
    with pytest.raises(AssertionError, match="reads as current"):
        assert_gap_is_stale_not_fresh(_claims_fresh, minutes, t, "heart_rate", gap_start)


def test_a_builder_that_hides_the_gap_in_its_counts_is_caught_by_the_count_requirement() -> None:
    minutes, t, gap_start = _gapped_case()
    with pytest.raises(AssertionError, match="not visible"):
        assert_gap_is_stale_not_fresh(_hides_the_gap_in_counts, minutes, t, "heart_rate", gap_start)


# --- the name gate: an allow-list, with the deny-list as a second layer ---------------------

EXPECTED_FORBIDDEN_PARTS = {
    "news2", "tier_a", "tier_b", "tier_c", "finding", "kdigo", "arbiter", "escalat",
    "rank", "priority", "label", "outcome", "event",
}  # fmt: skip


def test_the_deny_list_is_exactly_the_reviewed_one() -> None:
    assert set(FORBIDDEN_NAME_PARTS) == EXPECTED_FORBIDDEN_PARTS


@pytest.mark.parametrize("part", sorted(EXPECTED_FORBIDDEN_PARTS))
def test_every_deny_list_term_is_exercised(part: str) -> None:
    with pytest.raises(AssertionError, match="verdict or the outcome"):
        assert_no_verdict_features([f"ctx__comorbidity_{part}"])


@pytest.mark.parametrize(
    "name",
    ["sofa__last", "mews_score", "heart_rate__news2_band", "heart_rate__mean_all", "hr_last"],
)
def test_names_outside_the_declared_schema_fail_even_without_a_deny_term(name: str) -> None:
    with pytest.raises(AssertionError, match="outside the declared schema"):
        assert_feature_names_allowed(["heart_rate__last", name])


def test_the_reference_builder_stays_inside_the_schema() -> None:
    assert_feature_names_allowed(reference_features(PATIENTS[0][1], MINUTES - 1))
    assert m4_leakage.FEATURE_NAME_RE.match("lactate__age_h")
    assert m4_leakage.FEATURE_NAME_RE.match("ctx__comorbidity_chf")


def test_a_schema_name_with_a_verdict_term_is_still_caught_by_the_second_layer() -> None:
    with pytest.raises(AssertionError, match="verdict or the outcome"):
        assert_feature_names_allowed(["ctx__comorbidity_label_leak"])
