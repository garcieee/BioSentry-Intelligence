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
import warnings
from collections.abc import Callable, Sequence
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
    # a 12 s pause drags the mean interval to 2.7 s, past the bound; the median stays 0.8 s
    assert isinstance(rb.rr_features(_peaks([200, 200, 200, 3000, 200, 200])), dict)


def test_the_rate_bounds_use_the_sampling_rate_given() -> None:
    assert isinstance(rb.rr_features(_peaks([700] * 6), fs=500.0), dict)  # 1.4 s at 500 Hz
    assert rb.rr_features(_peaks([700] * 6), fs=250.0) == "implausible_rate"  # 2.8 s at 250 Hz


def test_the_robust_statistic_is_relative_to_the_median_interval() -> None:
    # intervals 100 200 100 200 100 600 samples: median 150, mean 217; steps 100 100 100 100 500
    got = rb.rr_features(_peaks([100, 200, 100, 200, 100, 600]))
    assert got["rmad"] == pytest.approx(100 / 150)


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
    with np.errstate(all="raise"):  # undefined must be a decision, not a 0/0 that happened
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
    assert rb.match_beats(reference, np.array([90.0, 210.0, 300.0]), 10.0) == (3, 0, 0)  # +-10 in
    assert rb.match_beats(reference, np.array([89.0, 211.0, 300.0]), 10.0) == (1, 2, 2)  # +-11 out
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
                [0.60, 0.20, 0.10, 0.10],  # p(AF) sits exactly on the head threshold: AF
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
        "head_specificity": 1 / 3,  # the 0.20 and the 0.50 windows are called AF
        "head_ppv": 3 / 5,
        "base_sensitivity": 1 / 3,
        "base_specificity": 1 / 3,
        "base_ppv": 1 / 3,
        "delta_sensitivity": 2 / 3,
        "delta_specificity": 0.0,
        "delta_ppv": 3 / 5 - 1 / 3,
        "head_burden_mae": (1 / 2 + 1 / 3) / 2,
        "base_burden_mae": (1 / 6 + 0.0) / 2,
        # head specificity 1/3: the smallest baseline threshold keeping one of its three negatives
        # below it is 0.2, which calls every window but the 0.1 one AF
        "base_sensitivity_at_head_specificity": 1.0,
        "base_specificity_at_head_specificity": 1 / 3,
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
        "typical_peaks": rb.TYPICAL_PEAKS,
        "integration_s": rb.INTEGRATION_S,
        "refine_reach_s": rb.REFINE_REACH_S,
        "band_hz": list(rb.BAND_HZ),
        "kernel_span_s": rb.KERNEL_SPAN_S,
    }
    validation = sel["validation"]
    assert validation["specificity"] >= rb.MIN_SPECIFICITY
    assert set(validation["auroc_by_feature"]) == set(rb.FEATURES)
    best = max(validation["auroc_by_feature"], key=validation["auroc_by_feature"].get)
    assert sel["feature"] == best


def test_the_reference_threshold_is_skipped_when_a_side_has_no_negatives() -> None:
    # the baseline refused every non-AF window, the head did not: nothing to match its
    # specificity against, so the row is undefined rather than an error
    only_af_left = rb.Record(
        np.array([1, 0]),
        np.array([[0.1, 0.8, 0.05, 0.05], [0.8, 0.1, 0.05, 0.05]]),
        np.array([0.9, float("nan")]),
    )
    got = rb.baseline_stats([only_af_left], head_threshold=0.2, base_threshold=0.5)
    assert got["head_specificity"] == 1.0
    assert np.isnan(got["base_sensitivity_at_head_specificity"])
    assert np.isnan(got["base_specificity_at_head_specificity"])
    # the head refused every non-AF window, the baseline did not: the head's specificity is
    # undefined, so there is no level to match
    head_has_none = rb.Record(
        np.array([1, 0]),
        np.array([[0.1, 0.8, 0.05, 0.05], [0.1, 0.2, 0.1, 0.6]]),
        np.array([0.9, 0.1]),
    )
    got = rb.baseline_stats([head_has_none], head_threshold=0.2, base_threshold=0.5)
    assert np.isnan(got["head_specificity"])
    assert np.isnan(got["base_sensitivity_at_head_specificity"])


# --- the detector's parts -----------------------------------------------------------------


def test_the_detector_wants_one_dimensional_windows() -> None:
    with pytest.raises(ValueError, match="1-D"):
        rb.detect_r_peaks(np.zeros((2, 2500)))


def test_a_window_no_longer_than_the_filter_span_has_no_beats() -> None:
    pulse = np.zeros(126)
    pulse[63] = 1.0
    assert rb.detect_r_peaks(pulse[:125]).size == 0  # the 0.5 s kernel is 125 samples long
    assert rb.detect_r_peaks(pulse).size == 1


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([0, 1, 2, 1, 0], [2]),
        ([0, 3, 0, 2, 0], [1, 3]),
        ([0, 1, 1, 0], [1]),  # the first sample of a flat top, not the second
        ([0, 1, 2, 3], []),
        ([1, 1, 1], []),
        ([1, 2], []),
    ],
    ids=["one peak", "two peaks", "flat top", "rising", "flat", "too short"],
)
def test_local_maxima_are_strictly_above_the_left_and_not_below_the_right(
    values: list[int], expected: list[int]
) -> None:
    assert rb._local_maxima(np.array(values, dtype=np.float64)).tolist() == expected


def test_suppression_keeps_the_best_first_and_drops_anything_within_the_radius() -> None:
    assert rb._suppress(np.array([10, 15, 16, 30]), 40, 5) == [10, 16, 30]  # 15 is 5 away: dropped
    assert rb._suppress(np.array([15, 10, 16]), 40, 5) == [15]  # best first decides who stays
    assert rb._suppress(np.array([2, 7]), 40, 5) == [2]  # the window edge clips the zone only
    assert rb._suppress(np.array([2, 8]), 40, 5) == [2, 8]
    assert rb._suppress(np.array([38, 39]), 40, 5) == [38]


def _energy(heights: Sequence[float], positions: Sequence[int], size: int = 1000) -> np.ndarray:
    energy = np.zeros(size)
    for p, h in zip(positions, heights, strict=True):
        energy[p] = h
    return energy


_SIX = [100, 250, 400, 550, 700, 850]


def test_a_peak_is_kept_from_exactly_a_quarter_of_the_typical_one() -> None:
    cand = np.array(_SIX)
    at = rb._gate(_energy([100, 100, 100, 100, 100, 25.0], _SIX), cand, 62)
    assert at.tolist() == _SIX
    below = rb._gate(_energy([100, 100, 100, 100, 100, 24.9], _SIX), cand, 62)
    assert below.tolist() == _SIX[:5]


def test_the_typical_peak_is_the_median_of_the_five_largest() -> None:
    cand = np.array(_SIX)
    one_huge = rb._gate(_energy([1000, 100, 100, 100, 100, 30], _SIX), cand, 62)
    assert one_huge.tolist() == _SIX  # a single artefact does not raise the bar
    three_huge = rb._gate(_energy([1000, 1000, 1000, 100, 100, 30], _SIX), cand, 62)
    assert sorted(three_huge.tolist()) == _SIX[:3]  # three of five: that is the typical peak
    few = rb._gate(_energy([100, 10], [100, 400]), np.array([100, 400]), 62)
    assert few.tolist() == [100]  # the median of two is 55, a quarter 13.75
    three = rb._gate(_energy([100, 50, 20], [100, 400, 700]), np.array([100, 400, 700]), 62)
    assert sorted(three.tolist()) == [100, 400, 700]  # median 50, a quarter 12.5


def test_the_gate_applies_the_refractory_period_by_height() -> None:
    cand = np.array([100, 162, 163, 400])
    energy = _energy([100, 90, 95, 100], [100, 162, 163, 400])
    kept = rb._gate(energy, cand, 62)
    assert sorted(kept.tolist()) == [100, 163, 400]  # 162 is 62 away from 100 (dropped), 163 is 63
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no median of nothing on the way to an empty answer
        assert rb._gate(np.zeros(100), np.zeros(0, dtype=np.int64), 62).size == 0


def test_refinement_moves_to_the_largest_magnitude_within_reach_inclusive() -> None:
    y = np.zeros(100)
    y[40], y[45], y[47] = -3.0, 2.0, 5.0
    assert rb._refine(y, np.array([42]), 5).tolist() == [47]  # k + reach is inside
    y[48] = 6.0
    assert rb._refine(y, np.array([42]), 5).tolist() == [47]  # k + reach + 1 is outside
    assert rb._refine(y, np.array([42]), 3).tolist() == [40]  # the larger magnitude, either sign
    y2 = np.zeros(100)
    y2[0] = 4.0
    assert rb._refine(y2, np.array([2]), 5).tolist() == [0]  # clipped at the window start
    assert rb._refine(y, np.array([], dtype=np.int64), 5).size == 0


def test_windowed_detection_is_the_per_window_detections_shifted_and_drops_the_tail() -> None:
    x = np.array(synth_ecg(duration_s=30.0, seed=9).samples)[:6200]
    got = rb.detect_windowed(x)
    first = rb.detect_r_peaks(x[:2500])
    second = rb.detect_r_peaks(x[2500:5000]) + 2500
    assert got.tolist() == first.tolist() + second.tolist()
    assert got.max() < 5000  # the 1200 samples left over are not a window


# --- the windows scored ---------------------------------------------------------------------


def test_only_fully_labelled_complete_windows_with_a_clear_majority_are_scored() -> None:
    w = 100
    lab = np.zeros(8 * w + 50, dtype=np.int8)
    x = np.ones(len(lab))
    lab[0:w] = 1  # all AF
    lab[w : 2 * w] = 0
    lab[w : w + 5] = 1  # 95% N
    lab[2 * w : 3 * w] = 2
    lab[2 * w : 2 * w + 15] = 0  # 85% other: no clear majority
    lab[3 * w + 40] = -1  # one unlabelled sample
    lab[4 * w : 5 * w] = 1  # a missing sample, not a label problem
    x[4 * w + 7] = np.nan
    lab[5 * w : 6 * w] = 1
    lab[5 * w : 5 * w + 10] = 0  # exactly 90% AF
    lab[6 * w : 7 * w] = 1
    lab[6 * w : 6 * w + 11] = 0  # 89%
    lab[7 * w : 8 * w] = 2
    starts, labels = rb.label_windows(lab, x, window=w)
    assert starts.tolist() == [0, w, 5 * w, 7 * w]
    assert labels.tolist() == [1, 0, 1, 2]


# --- the choice that is pinned --------------------------------------------------------------


def _validation_table(good: str) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    rng = np.random.default_rng(2)
    y = np.array([1] * 30 + [0] * 60 + [2] * 20 + [3] * 10)
    table = {k: rng.normal(size=len(y)) for k in rb.FEATURES}
    signal = np.where(y == 1, 3.0, 0.0) + rng.normal(0.0, 0.5, len(y))
    signal[y == 3] = 100.0  # noisy windows would drag the threshold up if they counted as negatives
    table[good] = signal
    for column in table.values():
        column[:3] = np.nan  # three AF windows the baseline refused
    return y, table


@pytest.mark.parametrize("good", ["rmad", "cv"])
def test_the_choice_uses_accepted_af_against_normal_and_other_only(good: str) -> None:
    y, table = _validation_table(good)
    got = rb.choose_on_validation(y, table)
    assert got["feature"] == good
    assert got["accepted"] == 117
    # 30 AF less 3 refused; 60 N and 20 Other; the 10 Noisy windows are in neither set
    assert (got["af_windows"], got["non_af_windows"]) == (27, 80)
    rest = ((y == 0) | (y == 2)) & ~np.isnan(table[good])
    scores = table[good]
    negatives = np.sort(scores[rest])
    candidates = np.unique(scores[((y == 1) | rest) & ~np.isnan(scores)])
    expected = next(
        c for c in candidates if np.searchsorted(negatives, c, side="left") / len(negatives) >= 0.95
    )
    assert got["threshold"] == expected
    called = scores >= expected
    af = (y == 1) & ~np.isnan(scores)
    assert got["sensitivity"] == pytest.approx((called & af).sum() / af.sum())
    assert got["specificity"] == pytest.approx((~called & rest).sum() / rest.sum())
    assert got["specificity"] >= 0.95
    assert got["auroc_by_feature"][good] == pytest.approx(
        rb.auroc(af[af | rest], scores[af | rest])
    )
    against_n = af | ((y == 0) & ~np.isnan(scores))
    against_other = af | ((y == 2) & ~np.isnan(scores))
    assert got["auroc_selected_af_vs_n"] == pytest.approx(
        rb.auroc(af[against_n], scores[against_n])
    )
    assert got["auroc_selected_af_vs_other"] == pytest.approx(
        rb.auroc(af[against_other], scores[against_other])
    )


# --- the table of statistics ----------------------------------------------------------------


def test_the_statistics_table_has_nan_exactly_where_a_window_was_refused() -> None:
    good = np.array(synth_ecg(duration_s=10.0, seed=1).samples[:2500])
    broken = good.copy()
    broken[10] = np.nan
    flat = np.zeros(2500)
    table, reasons = rb._features_table(np.stack([good, broken, flat]))
    assert reasons == {"incomplete_window": 1, "too_few_beats": 1}
    for key in rb.FEATURES:
        assert np.isfinite(table[key][0])
        assert np.isnan(table[key][1:]).all()


def test_only_beats_inside_whole_windows_are_expected() -> None:
    beats = np.array([5.0, 2499.0, 2500.0, 4999.0, 5000.0, 5001.0, 6000.0])
    assert rb.beats_covered(beats, 7200).tolist() == [5.0, 2499.0, 2500.0, 4999.0]
    assert rb.beats_covered(beats, 5000).tolist() == [5.0, 2499.0, 2500.0, 4999.0]
    assert rb.beats_covered(beats, 4999).tolist() == [5.0, 2499.0]
    assert rb.beats_covered(beats, 100, window=100).tolist() == [5.0]


def test_rhythm_annotations_hold_until_the_next_annotation_of_any_kind() -> None:
    lab = rb.rhythm_labels([0, 100, 200, 300], ["(N", "(AFIB", "(VT", "(N"], 500)
    assert (lab[0:100] == 0).all()
    assert (lab[100:200] == 1).all()
    assert (lab[200:300] == -1).all()  # an unknown rhythm is not painted over by the one before
    assert (lab[300:500] == 0).all()
    assert lab.dtype == np.int8


def test_rhythm_labels_map_flutter_to_af_and_junctional_to_other_and_strip_nul() -> None:
    lab = rb.rhythm_labels([0, 10, 20, 30], ["(AFL\x00", "(J", "(AFIB\x00\x00", None], 40)
    assert lab.tolist() == [1] * 10 + [2] * 10 + [1] * 10 + [-1] * 10
    scaled = rb.rhythm_labels([0, 36], ["(N", "(AFIB"], 100, scale=250 / 360)
    assert (scaled[:25] == 0).all()
    assert (scaled[25:] == 1).all()
    assert (scaled[:25] != 1).all()


def test_softmax_rows_sum_to_one_and_survive_large_logits() -> None:
    got = rb._softmax(np.array([[0.0, 0.0, 0.0, 0.0], [1000.0, 0.0, -1000.0, 999.0]]))
    assert got.sum(axis=1) == pytest.approx([1.0, 1.0])
    assert got[0].tolist() == pytest.approx([0.25] * 4)
    assert np.isfinite(got).all()
    assert got[1, 0] == pytest.approx(1 / (1 + np.exp(-1)))
    assert got[1, 3] == pytest.approx(np.exp(-1) / (1 + np.exp(-1)))


def _gain(kernel: np.ndarray, lo_hz: float, hi_hz: float) -> tuple[float, float]:
    spectrum = np.abs(np.fft.rfft(kernel, 8192))
    freq = np.fft.rfftfreq(8192, 1 / FS)
    band = spectrum[(freq >= lo_hz) & (freq <= hi_hz)]
    return float(band.min()), float(band.max())


def test_the_detector_filter_is_a_5_to_15_hz_band_pass_of_unit_gain() -> None:
    kernel = rb._band_kernel(float(FS))
    assert kernel.size == 125  # 0.5 s, odd
    assert np.allclose(kernel, kernel[::-1])  # linear phase: peaks do not move
    assert abs(float(kernel.sum())) < 0.01  # no DC
    assert _gain(kernel, 0.0, 2.0)[1] < 0.02  # baseline wander and respiration
    lo, hi = _gain(kernel, 8.0, 12.0)
    assert lo > 0.95
    assert hi < 1.05  # unit gain in the QRS band
    assert _gain(kernel, 20.0, 125.0)[1] < 0.01  # EMG, mains and above


def test_the_pinned_selection_names_every_detector_constant() -> None:
    sel = json.loads((TRAINING / "rr_baseline_selection.json").read_text(encoding="utf-8"))
    assert sel["detector"] == {
        "fs": 250,
        "window": 2500,
        "min_beats": 6,
        "median_rr_s": [0.3, 2.0],
        "refractory_s": 0.25,
        "threshold_fraction": 0.25,
        "typical_peaks": 5,
        "integration_s": 0.15,
        "refine_reach_s": 0.1,
        "band_hz": [5.0, 15.0],
        "kernel_span_s": 0.5,
    }
    assert rb.MIN_SPECIFICITY == 0.95
    assert rb.FEATURES == ("nrmssd", "cv", "tpr", "rmad")


def test_refined_peaks_that_landed_close_keep_only_the_stronger_one() -> None:
    y = np.zeros(400)
    y[100], y[112] = 1.0, 2.0
    assert rb._merge(y, np.array([100, 112]), 62).tolist() == [112]
    y[100] = -3.0  # magnitude, not sign
    assert rb._merge(y, np.array([112, 100]), 62).tolist() == [100]
    assert rb._merge(y, np.array([100, 200]), 62).tolist() == [100, 200]
    assert rb._merge(y, np.array([], dtype=np.int64), 62).size == 0


def test_the_typical_peak_is_made_of_five_not_three_and_not_more() -> None:
    cand = np.array(_SIX)
    # the three largest are huge: median of five is 100 (a quarter: 25, so 30 stays);
    # median of three would be 1000
    assert len(rb._gate(_energy([1000, 1000, 100, 100, 100, 30], _SIX), cand, 62)) == 6
    eight = [100, 250, 400, 550, 700, 850, 1000, 1150]
    heights = [100, 100, 100, 10, 5, 1, 1, 1]
    kept = rb._gate(_energy(heights, eight, size=1300), np.array(eight), 62)
    # the median of the five largest is 100, so the bar is 25; seven would give 10 and let 10 in
    assert kept.tolist().count(550) == 0
    assert sorted(kept.tolist()) == [100, 250, 400]


def test_a_refused_window_ranks_below_even_a_perfectly_regular_window() -> None:
    nan = float("nan")
    rec = rb.Record(
        np.array([1, 0, 0]),
        np.array([[0.1, 0.8, 0.05, 0.05], [0.8, 0.1, 0.05, 0.05], [0.7, 0.2, 0.05, 0.05]]),
        np.array([nan, 0.0, 0.0]),  # the AF window refused; two regular windows score exactly 0
    )
    got = rb.baseline_stats([rec], head_threshold=0.2, base_threshold=0.5)
    assert got["base_auroc_all"] == 0.0  # not 0.5, which a refusal scored as 0 would tie to


def test_the_burden_error_is_absolute_when_a_method_underestimates() -> None:
    rec = rb.Record(
        np.array([1, 1, 0, 0]),
        np.array([[0.8, 0.1, 0.05, 0.05]] * 4),  # the head sees no AF at all
        np.array([0.9, 0.9, 0.1, 0.1]),
    )
    got = rb.baseline_stats([rec], head_threshold=0.2, base_threshold=0.5)
    assert got["head_burden_mae"] == pytest.approx(0.5)
    assert got["base_burden_mae"] == pytest.approx(0.0)


# --- the card quotes what was measured ------------------------------------------------------

MODEL_DIR = ROOT / "models" / "tier_b" / "arrhythmia"


def _card() -> str:
    return " ".join((MODEL_DIR / "card.md").read_text(encoding="utf-8").split())


def _measurements() -> dict[str, object]:
    data = json.loads((MODEL_DIR / "m3_exit_measurements.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _interval(m: dict[str, dict[str, float]], key: str) -> str:
    v = m[key]
    return f"{v['point']:.3f} ({v['lo']:.3f}-{v['hi']:.3f})"


def _difference(m: dict[str, dict[str, float]], key: str) -> str:
    v = m[key]
    return f"{v['point']:+.3f} ({v['lo']:+.3f} to {v['hi']:+.3f})"


def _percent(m: dict[str, dict[str, float]], key: str) -> str:
    v = m[key]
    return f"{v['point'] * 100:.1f}% ({v['lo'] * 100:.1f}-{v['hi'] * 100:.1f}%)"


def test_the_measurements_file_is_the_run_the_selection_pinned() -> None:
    sel = json.loads((TRAINING / "rr_baseline_selection.json").read_text(encoding="utf-8"))
    got = _measurements()["rr_baseline_afdb"]
    assert isinstance(got, dict)
    assert got["feature"] == sel["feature"]
    assert got["base_threshold"] == sel["threshold"]
    assert (got["windows"], got["records"]) == (83863, 23)
    assert got["bootstrap"] == {"resamples": rb.N_BOOT, "seed": rb.SEED, "unit": "record"}
    assert got["head_threshold"] == pytest.approx(0.20)
    undefined = [k for k, v in got["metrics"].items() if v["undefined_draws"]]
    assert not undefined, undefined


def test_the_card_quotes_the_baseline_numbers_as_measured() -> None:
    card = _card()
    afdb = _measurements()["rr_baseline_afdb"]
    assert isinstance(afdb, dict)
    m = afdb["metrics"]
    for key in (
        "head_auroc_all",
        "base_auroc_all",
        "head_auroc_both",
        "base_auroc_both",
        "head_sensitivity",
        "base_sensitivity",
        "head_specificity",
        "base_specificity",
        "head_ppv",
        "base_ppv",
        "head_burden_mae",
        "base_burden_mae",
        "base_sensitivity_at_head_specificity",
    ):
        assert _interval(m, key) in card, key
    for key in (
        "delta_auroc_all",
        "delta_auroc_both",
        "delta_sensitivity",
        "delta_specificity",
        "delta_ppv",
    ):
        assert _difference(m, key) in card, key
    for key in ("head_refused", "base_refused"):
        assert _percent(m, key) in card, key
    assert f"{m['both_accepted']['point'] * 100:.1f}%" in card
    assert f"{afdb['af_prevalence'] * 100:.1f}%" in card
    assert f"threshold {afdb['base_threshold']:.3f}" in card


def test_the_card_quotes_the_detector_check_and_the_validation_choice() -> None:
    card = _card()
    ds1 = _measurements()["rr_detector_ds1"]
    assert isinstance(ds1, dict)
    tp, _fp, fn = ds1["tp_fp_fn"]
    assert f"sensitivity {ds1['sensitivity']:.3f} and PPV {ds1['ppv']:.3f}" in card
    assert f"{tp:,} of {tp + fn:,} beats in {ds1['records']} records" in card
    assert ds1["records"] == len(rb.DS1)
    val = json.loads((TRAINING / "rr_baseline_selection.json").read_text(encoding="utf-8"))
    auc = val["validation"]["auroc_by_feature"]
    quoted = f"{auc['rmad']:.3f}, against {auc['nrmssd']:.3f}, {auc['cv']:.3f} and {auc['tpr']:.3f}"
    assert quoted in card
    assert f"sensitivity {val['validation']['sensitivity']:.3f} at specificity" in card
    assert f"{val['validation']['auroc_selected_af_vs_n']:.3f} against N" in card
    assert f"{val['validation']['auroc_selected_af_vs_other']:.3f} against Other" in card


def test_the_card_quotes_the_latency_as_measured() -> None:
    card = _card()
    lat = _measurements()["latency"]
    assert isinstance(lat, dict)
    for key, label in (("ort_fp32", "ONNX Runtime FP32"), ("ort_int8", "ONNX Runtime INT8")):
        v = lat[key]
        ms, minute = v["ms_per_window"], v["ms_per_patient_minute"]
        row = (
            f"| {label} (network only) | {ms['p50']:.3f} ms | {ms['p95']:.3f} ms | "
            f"{minute['p50']:.2f} / {minute['p95']:.2f} ms | {v['peak_rss_mb']:.1f} MB |"
        )
        assert row in card, key
        assert v["threads"] == 1
        assert v["batch"] == 1
    for key, label in (("numpy_fp32", "numpy FP32"), ("numpy_int8", "numpy INT8")):
        v = lat[key]
        row = (
            f"| {label} (whole labeller) | {v['p50']:.2f} ms | {v['p95']:.2f} ms | "
            f"{v['per_minute_p50']:.2f} / {v['per_minute_p95']:.2f} ms | "
            f"{v['peak_rss_mb']:.1f} MB |"
        )
        assert row in card, key


def test_the_card_says_what_it_must_about_afdb_and_the_exit_gate() -> None:
    card = _card()
    for needle in (
        "this head was scored on it repeatedly",
        "the only decision those runs informed was",
        "is the Evaluator's ruling, not this card's",
        "a refusal is never scored as regular",
        "pinned in `training/rr_baseline_selection.json` before AFDB was scored",
        "The M3 exit gate is not met by this model or this card",
        "Outstanding at least: a PVC metric and MindSpore Lite parity",
        "10.13026/C2F305",
        "https://physionet.org/content/mitdb/view-license/1.0.0/",
        "Paced records 102, 104, 107, 217 are out by convention",
        "202 is out because it is the same subject and tape as 201",
        "DS2 is untouched",
    ):
        assert needle in card, needle


def test_the_card_does_not_call_afdb_held_out_until_the_evaluator_rules() -> None:
    # The Orchestrator's instruction: the word waits for the Evaluator's ruling. When that ruling
    # exists, delete this test and say so in the card.
    assert "held-out" not in _card().lower()
