"""M4 leakage skeleton on the CP3b generator: the checks pass for the reference builder and
demonstrably fail for builders that leak, impute or smuggle in a verdict."""

import ast
import math
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pytest
from m4_leakage import (
    FeatureBuilder,
    Series,
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
