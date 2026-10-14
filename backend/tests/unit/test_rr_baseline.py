"""The classical RR-irregularity baseline (training/rr_baseline.py): detector, statistics, refusal
rules and metrics. The module is numpy only at import, so every pure function is exercised here
without scipy; the commands that read PhysioNet data are not (they need the corpora).

What is pinned: the numbers a reader of the card would otherwise have to trust. The statistics
against hand computed series, the refusal boundaries to the sample, AUROC against brute force,
the threshold rule against its definition, the bootstrap against the seeded generator, and
head versus baseline on a hand built pair of records.
"""

import importlib.util
import json
import sys
from collections.abc import Callable
from itertools import product
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from synth_ecg import synth_ecg

ROOT = Path(__file__).resolve().parents[3]
TRAINING = ROOT / "training"
FS = 250


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rr_baseline", TRAINING / "rr_baseline.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rr_baseline"] = module
    spec.loader.exec_module(module)
    return module


rb = _load()


def _peaks(rr_samples: list[int], start: int = 50) -> np.ndarray:
    return np.concatenate(([start], start + np.cumsum(rr_samples))).astype(np.int64)


# --- the statistics -----------------------------------------------------------------------


def test_a_regular_rhythm_has_zero_irregularity() -> None:
    got = rb.rr_features(_peaks([200] * 7))
    assert set(got) == {"nrmssd", "cv", "tpr", "rmad"}
    for key, value in got.items():
        assert value == pytest.approx(0.0, abs=1e-12), key  # SD of equal floats is rounding noise


def test_alternating_intervals_have_the_hand_computed_statistics() -> None:
    # RR 0.6, 1.0, 0.6, 1.0, 0.6, 1.0 s: mean 0.8, every step +-0.4, SD 0.2, all turning points
    got = rb.rr_features(_peaks([150, 250] * 3))
    assert got["nrmssd"] == pytest.approx(0.5)
    assert got["cv"] == pytest.approx(0.25)
    assert got["tpr"] == pytest.approx(1.0)
    assert got["rmad"] == pytest.approx(0.5)


def test_one_ectopic_pair_moves_rmssd_but_not_the_robust_statistic() -> None:
    # 13 intervals, one short-long pair: 3 of the 12 steps are non-zero, so their median is 0
    got = rb.rr_features(_peaks([200] * 5 + [150, 250] + [200] * 6))
    assert got["rmad"] == 0.0
    assert got["nrmssd"] == pytest.approx(np.sqrt(15000 / 12) / FS / 0.8)
    assert got["cv"] == pytest.approx(np.sqrt((2500 + 2500) / 13) / 200)


def test_turning_points_count_only_strict_extrema() -> None:
    # 0.8 0.8 1.0 1.0 0.8 0.8: a step up and a step down, but no interior point is an extremum
    assert rb.rr_features(_peaks([200, 200, 250, 250, 200, 200]))["tpr"] == 0.0
    # 0.8 1.0 0.8 0.8 1.0 0.8: the two 1.0 are peaks, the two 0.8 plateau points are not
    got = rb.rr_features(_peaks([200, 250, 200, 200, 250, 200]))
    assert got["tpr"] == pytest.approx(2 / 4)


# --- what is refused ----------------------------------------------------------------------


def test_fewer_than_six_beats_is_refused_and_six_is_not() -> None:
    assert rb.rr_features(_peaks([200] * 4)) == "too_few_beats"  # 5 peaks
    assert isinstance(rb.rr_features(_peaks([200] * 5)), dict)  # 6 peaks
    assert rb.rr_features(np.zeros(0, dtype=np.int64)) == "too_few_beats"


@pytest.mark.parametrize(
    ("interval", "accepted"),
    [(74, False), (75, True), (500, True), (501, False)],
    ids=["above 200 bpm", "200 bpm", "30 bpm", "below 30 bpm"],
)
def test_the_rate_bounds_are_inclusive_on_the_median_interval(
    interval: int, accepted: bool
) -> None:
    got = rb.rr_features(_peaks([interval] * 6))
    assert isinstance(got, dict) is accepted
    if not accepted:
        assert got == "implausible_rate"


def test_one_long_gap_among_regular_beats_does_not_refuse_by_the_median() -> None:
    assert isinstance(rb.rr_features(_peaks([200, 200, 200, 600, 200, 200])), dict)


def test_a_window_with_a_non_finite_sample_is_refused_never_filled() -> None:
    ecg = np.array(synth_ecg(duration_s=10, seed=1).samples[:2500])
    assert isinstance(rb.window_features(ecg), dict)
    for bad in (np.nan, np.inf, -np.inf):
        broken = ecg.copy()
        broken[1200] = bad
        assert rb.window_features(broken) == "incomplete_window"
        with pytest.raises(ValueError, match="never fill"):
            rb.detect_r_peaks(broken)


# --- the detector -------------------------------------------------------------------------


def _detections(x: np.ndarray) -> np.ndarray:
    found: list[int] = []
    for s0 in range(0, len(x) - 2500 + 1, 2500):
        found += (rb.detect_r_peaks(x[s0 : s0 + 2500]) + s0).tolist()
    return np.array(found, dtype=np.float64) / FS


def _beats_found(x: np.ndarray, truth_s: tuple[float, ...]) -> tuple[int, int, int]:
    covered = (len(x) // 2500) * 2500 / FS
    truth = np.unique(np.round([t for t in truth_s if t < covered], 4))  # the generator repeats one
    got = rb.match_beats(truth, _detections(x), 0.150)
    return int(got[0]), int(got[1]), int(got[2])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"hr_bpm": 70},
        {"hr_bpm": 50},
        {"hr_bpm": 110},
        {"irregular": True},
        {"noise_sd_mv": 0.12},
        {"wander_mv": 0.8},
        {"pvc_after_s": (20.0, 41.0, 77.0)},
    ],
    ids=["70 bpm", "50 bpm", "110 bpm", "irregular", "noisy", "wander", "with PVCs"],
)
def test_every_beat_of_a_synthetic_recording_is_found_once(kwargs: dict[str, object]) -> None:
    ecg = synth_ecg(duration_s=120.0, seed=3, **kwargs)  # type: ignore[arg-type]
    tp, fp, fn = _beats_found(np.array(ecg.samples), ecg.r_times_s)
    assert (fp, fn) == (0, 0)
    assert tp > 90


@pytest.mark.parametrize(
    "transform",
    [lambda v: v + 5.0, lambda v: v * 1000.0, lambda v: -v],
    ids=["dc offset", "gain", "inverted"],
)
def test_detection_is_unchanged_by_offset_gain_and_polarity(
    transform: Callable[[np.ndarray], np.ndarray],
) -> None:
    x = np.array(synth_ecg(duration_s=60.0, seed=7).samples)
    assert _detections(transform(x)).tolist() == _detections(x).tolist()


def test_one_huge_artefact_does_not_hide_the_real_beats() -> None:
    t = np.arange(2500) / FS
    x = np.zeros(2500)
    for k in range(10):
        x += np.exp(-0.5 * ((t - (0.5 + 0.8 * k)) / 0.012) ** 2)
    x += 30.0 * np.exp(-0.5 * ((t - 9.2) / 0.012) ** 2)  # thirty times a QRS
    assert rb.detect_r_peaks(x).size == 11


def test_a_flat_or_too_short_window_has_no_beats_and_does_not_raise() -> None:
    assert rb.detect_r_peaks(np.zeros(2500)).size == 0
    assert rb.detect_r_peaks(np.full(2500, 3.0)).size == 0
    assert rb.detect_r_peaks(np.random.default_rng(0).normal(size=100)).size == 0
    assert rb.detect_r_peaks(np.zeros(0)).size == 0


def test_two_complexes_closer_than_the_refractory_period_are_one_beat() -> None:
    t = np.arange(2500) / FS

    def window(extra_gap_s: float) -> np.ndarray:
        x = np.zeros(2500)
        times = [0.5 + 0.8 * k for k in range(10)]
        times.append(times[4] + extra_gap_s)
        for tb in times:
            x += np.exp(-0.5 * ((t - tb) / 0.012) ** 2)
        return x

    assert rb.detect_r_peaks(window(0.20)).size == 10
    assert rb.detect_r_peaks(window(0.30)).size == 11


def test_a_small_bump_between_complexes_is_not_a_beat() -> None:
    t = np.arange(2500) / FS
    x = np.zeros(2500)
    for k in range(10):
        x += np.exp(-0.5 * ((t - (0.5 + 0.8 * k)) / 0.012) ** 2)  # QRS
        x += 0.1 * np.exp(-0.5 * ((t - (0.5 + 0.8 * k + 0.4)) / 0.012) ** 2)  # one tenth: noise
    assert rb.detect_r_peaks(x).size == 10


def test_detection_inside_a_window_does_not_depend_on_its_neighbours() -> None:
    x = np.array(synth_ecg(duration_s=30.0, seed=4).samples)
    alone = rb.detect_r_peaks(x[2500:5000])
    again = rb.detect_r_peaks(x[2500:5000].copy())
    assert alone.tolist() == again.tolist()


# --- AUROC, threshold and rates -----------------------------------------------------------


def _brute_auroc(positive: np.ndarray, score: np.ndarray) -> float:
    wins = 0.0
    for p, n in product(score[positive], score[~positive]):
        wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return float(wins / (int(positive.sum()) * int((~positive).sum())))


def test_auroc_matches_the_pairwise_definition_with_ties() -> None:
    rng = np.random.default_rng(11)
    for _ in range(20):
        positive = rng.random(40) < 0.4
        score = np.round(rng.normal(size=40) + positive * 0.7, 1)  # many ties
        if positive.all() or not positive.any():
            continue
        assert rb.auroc(positive, score) == pytest.approx(_brute_auroc(positive, score))


def test_auroc_extremes_and_undefined_cases() -> None:
    pos = np.array([True, True, False, False])
    assert rb.auroc(pos, np.array([0.9, 0.8, 0.2, 0.1])) == 1.0
    assert rb.auroc(pos, np.array([0.1, 0.2, 0.8, 0.9])) == 0.0
    assert rb.auroc(pos, np.array([0.5, 0.5, 0.5, 0.5])) == 0.5
    assert np.isnan(rb.auroc(np.array([True, True]), np.array([0.1, 0.9])))
    assert np.isnan(rb.auroc(np.array([False, False]), np.array([0.1, 0.9])))
    with_refusal = np.array([0.9, -np.inf, 0.2, -np.inf])
    assert rb.auroc(pos, with_refusal) == pytest.approx(_brute_auroc(pos, with_refusal))


def test_the_threshold_is_the_smallest_that_keeps_the_required_specificity() -> None:
    negatives = np.arange(100.0)  # 0..99
    positives = np.array([50.0, 94.5, 96.0, 200.0])
    score = np.concatenate([negatives, positives])
    positive = np.concatenate([np.zeros(100, bool), np.ones(4, bool)])
    t = rb.threshold_for_specificity(positive, score, 0.95)
    assert t == 94.5  # the smallest observed score with specificity >= 0.95 (95 of 100 below it)
    assert (negatives < t).mean() >= 0.95
    assert (negatives < 94.0).mean() < 0.95
    assert rb.rates(positive, score >= t)["specificity"] == pytest.approx(0.95)


def test_the_threshold_never_splits_a_tie_and_falls_back_above_the_maximum() -> None:
    # every negative ties with the top positive: no observed value reaches 95%, so nothing is called
    score = np.array([1.0] * 10 + [1.0] * 5)
    positive = np.array([False] * 10 + [True] * 5)
    t = rb.threshold_for_specificity(positive, score, 0.95)
    assert t > 1.0
    assert rb.rates(positive, score >= t)["specificity"] == 1.0
    with pytest.raises(ValueError, match="no negatives"):
        rb.threshold_for_specificity(np.array([True, True]), np.array([0.1, 0.2]))


def test_rates_count_exactly_and_report_undefined_as_nan_not_zero() -> None:
    positive = np.array([True, True, True, False, False, False, False])
    predicted = np.array([True, True, False, True, False, False, False])
    got = rb.rates(positive, predicted)
    assert (got["tp"], got["fn"], got["fp"], got["tn"]) == (2.0, 1.0, 1.0, 3.0)
    assert got["sensitivity"] == pytest.approx(2 / 3)
    assert got["specificity"] == pytest.approx(3 / 4)
    assert got["ppv"] == pytest.approx(2 / 3)
    none_called = rb.rates(positive, np.zeros(7, bool))
    assert np.isnan(none_called["ppv"])
    assert none_called["sensitivity"] == 0.0
    assert np.isnan(rb.rates(np.zeros(3, bool), np.zeros(3, bool))["sensitivity"])


# --- beat matching ------------------------------------------------------------------------


def test_matching_is_one_to_one_and_the_tolerance_is_inclusive() -> None:
    reference = np.array([100.0, 200.0, 300.0])
    assert rb.match_beats(reference, np.array([100.0, 200.0, 300.0]), 0.0) == (3, 0, 0)
    assert rb.match_beats(reference, np.array([110.0, 189.0, 310.0]), 10.0) == (2, 1, 1)
    # two detections near one reference: one is a true positive, the other a false positive
    assert rb.match_beats(reference, np.array([100.0, 104.0, 200.0, 300.0]), 10.0) == (3, 1, 0)
    # one detection between two references that are both within tolerance: it serves only one
    assert rb.match_beats(np.array([100.0, 108.0]), np.array([104.0]), 10.0) == (1, 0, 1)


def test_matching_counts_leftovers_and_empty_inputs() -> None:
    assert rb.match_beats(np.array([]), np.array([1.0, 2.0]), 5.0) == (0, 2, 0)
    assert rb.match_beats(np.array([1.0, 2.0]), np.array([]), 5.0) == (0, 0, 2)
    assert rb.match_beats(np.array([10.0, 500.0]), np.array([12.0, 700.0, 900.0]), 5.0) == (1, 2, 1)


# --- the bootstrap ------------------------------------------------------------------------


def test_the_bootstrap_resamples_whole_records_with_the_seeded_generator() -> None:
    records = [np.array([1.0, 1.0]), np.array([0.0]), np.array([0.0, 0.0, 1.0])]

    def mean_of_all(recs: list[np.ndarray]) -> dict[str, float]:
        return {"m": float(np.concatenate(recs).mean())}

    got = rb.record_bootstrap(records, mean_of_all, n_boot=9, seed=5)["m"]
    rng = np.random.default_rng(5)
    draws = [
        float(np.concatenate([records[i] for i in rng.integers(0, 3, 3)]).mean()) for _ in range(9)
    ]
    assert got["point"] == pytest.approx(0.5)  # the full sample, not a draw
    assert got["lo"] == pytest.approx(np.percentile(draws, 2.5))
    assert got["hi"] == pytest.approx(np.percentile(draws, 97.5))
    assert got["undefined_draws"] == 0.0


def test_the_bootstrap_is_reproducible_and_defaults_are_the_documented_ones() -> None:
    records = [np.array([float(i), float(i) + 0.5]) for i in range(6)]

    def spread(recs: list[np.ndarray]) -> dict[str, float]:
        return {"s": float(np.concatenate(recs).std())}

    first = rb.record_bootstrap(records, spread, 50, 3)
    assert first == rb.record_bootstrap(records, spread, 50, 3)
    assert first != rb.record_bootstrap(records, spread, 50, 4)
    assert (rb.N_BOOT, rb.SEED) == (1000, 20261014)


def test_draws_where_a_statistic_is_undefined_are_counted_and_left_out_of_the_interval() -> None:
    # only the first record has a positive window: draws that miss it have no AUROC at all
    records = [
        (np.array([True, False]), np.array([0.9, 0.1])),
        (np.array([False, False]), np.array([0.4, 0.3])),
        (np.array([False, False]), np.array([0.2, 0.6])),
    ]

    def stat(recs: list[tuple[np.ndarray, np.ndarray]]) -> dict[str, float]:
        y = np.concatenate([r[0] for r in recs])
        s = np.concatenate([r[1] for r in recs])
        return {"auroc": rb.auroc(y, s)}

    got = rb.record_bootstrap(records, stat, n_boot=200, seed=1)["auroc"]
    assert 0 < got["undefined_draws"] < 200
    assert np.isfinite(got["lo"])
    assert np.isfinite(got["hi"])


# --- head against baseline, on a hand built pair of records -------------------------------


def _pair() -> list[object]:
    nan = float("nan")
    a = rb.Record(
        np.array([1, 1, 0, 2]),
        np.array(
            [
                [0.05, 0.90, 0.03, 0.02],
                [0.60, 0.30, 0.05, 0.05],
                [0.70, 0.10, 0.10, 0.10],
                [0.10, 0.25, 0.15, 0.50],  # argmax Noisy: the head refuses it
            ]
        ),
        np.array([0.9, 0.2, nan, 0.6]),  # window 3 refused by the baseline
    )
    b = rb.Record(
        np.array([1, 0, 0]),
        np.array([[0.1, 0.7, 0.1, 0.1], [0.8, 0.1, 0.05, 0.05], [0.2, 0.5, 0.2, 0.1]]),
        np.array([0.4, 0.1, 0.5]),  # 0.5 sits exactly on the threshold: counted as AF
    )
    return [a, b]


def test_head_and_baseline_statistics_on_a_hand_built_pair_of_records() -> None:
    got = rb.baseline_stats(_pair(), head_threshold=0.2, base_threshold=0.5)
    expected = {
        "head_auroc_all": 11 / 12,
        "base_auroc_all": 8 / 12,  # the refusal is the lowest score, never a vote for AF
        "delta_auroc_all": 3 / 12,
        "head_auroc_accepted": 8 / 9,
        "base_auroc_accepted": 5 / 9,
        "head_auroc_both": 5 / 6,
        "base_auroc_both": 4 / 6,
        "delta_auroc_both": 1 / 6,
        "head_refused": 1 / 7,
        "base_refused": 1 / 7,
        "both_accepted": 5 / 7,
        "head_sensitivity": 1.0,
        "head_specificity": 2 / 3,
        "head_ppv": 3 / 4,
        "base_sensitivity": 1 / 3,
        "base_specificity": 1 / 3,
        "base_ppv": 1 / 3,
        "delta_sensitivity": 2 / 3,
        "delta_specificity": 1 / 3,
        "delta_ppv": 3 / 4 - 1 / 3,
        "head_burden_mae": (1 / 6 + 1 / 3) / 2,
        "base_burden_mae": (1 / 6 + 0.0) / 2,
        # head specificity 2/3: the smallest baseline threshold keeping 2 of its 3 negatives below
        # it is 0.7, which calls the 0.9 and the 0.7 windows AF
        "base_sensitivity_at_head_specificity": 1 / 3,
        "base_specificity_at_head_specificity": 2 / 3,
    }
    assert set(got) == set(expected)
    for key, value in expected.items():
        assert got[key] == pytest.approx(value), key


def test_a_refused_window_never_counts_as_normal_or_as_af_in_the_rates() -> None:
    # both methods refuse their one AF window: sensitivity is undefined, not 0 and not 1
    rec = rb.Record(
        np.array([1, 0]),
        np.array([[0.2, 0.2, 0.1, 0.5], [0.8, 0.1, 0.05, 0.05]]),
        np.array([float("nan"), 0.1]),
    )
    got = rb.baseline_stats([rec], head_threshold=0.2, base_threshold=0.5)
    assert np.isnan(got["head_sensitivity"])
    assert np.isnan(got["base_sensitivity"])
    assert got["head_specificity"] == 1.0
    assert got["head_refused"] == 0.5


# --- what is frozen -----------------------------------------------------------------------


def test_the_detector_check_can_only_reach_ds1() -> None:
    assert len(rb.DS1) == 22
    assert len(set(rb.DS1)) == 22
    assert "202" not in rb.DS1  # the same subject and tape as 201
    assert not {"102", "104", "107", "217"} & set(rb.DS1)  # paced records
    # DS2 is scored once, for the PVC metric: none of its record names is a literal in this file
    ds2 = [
        *("100", "103", "105", "111", "113", "117", "121", "123", "200", "202", "210"),
        *("212", "213", "214", "219", "221", "222", "228", "231", "232", "233", "234"),
    ]
    text = (TRAINING / "rr_baseline.py").read_text(encoding="utf-8")
    assert not [name for name in ds2 if f'"{name}"' in text]


def test_the_pinned_selection_matches_the_detector_it_was_made_with() -> None:
    sel = json.loads((TRAINING / "rr_baseline_selection.json").read_text(encoding="utf-8"))
    assert sel["feature"] in rb.FEATURES
    assert sel["detector"] == {
        "fs": rb.FS,
        "window": rb.WINDOW,
        "min_beats": rb.MIN_BEATS,
        "median_rr_s": [rb.MIN_MEDIAN_RR_S, rb.MAX_MEDIAN_RR_S],
        "refractory_s": rb.REFRACTORY_S,
        "threshold_fraction": rb.THRESHOLD_FRACTION,
    }
    validation = sel["validation"]
    assert validation["specificity"] >= rb.MIN_SPECIFICITY
    assert set(validation["auroc_by_feature"]) == set(rb.FEATURES)
    best = max(validation["auroc_by_feature"], key=validation["auroc_by_feature"].get)
    assert sel["feature"] == best
