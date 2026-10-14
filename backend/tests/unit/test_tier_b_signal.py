"""M2a: R peaks, HRV, burden and baseline score against exact synthetic truth; gaps stay gaps."""

import math

import numpy as np
import pytest
from no_imputation import assert_no_imputation
from synth_ecg import SynthEcg, f1_within, synth_ecg

from biosentry.domain.computed import Computed, NotComputed
from biosentry.domain.scoring.tier_b.burden import (
    BASELINE_MIN_VALID,
    HR_BURDEN_BPM,
    Baseline,
    hr_burden,
    robust_baseline,
    robust_z,
)
from biosentry.domain.scoring.tier_b.ecg import Beats, detect_beats
from biosentry.domain.scoring.tier_b.hrv import HrvValue, compute_hrv, hrv_window, nn_intervals
from biosentry.domain.signals import SignalInput
from biosentry.schemas import Provenance
from samples import provenance

PROV = Provenance.model_validate(provenance())


def _rmssd_ms(intervals: list[float]) -> float:
    d = np.diff(np.asarray(intervals))
    return float(np.sqrt(np.mean(d * d)) * 1000.0)


def _truth_nn(ecg: SynthEcg) -> list[float]:
    """Sinus-to-sinus intervals only: drop any interval that touches a premature beat or the
    pause that follows it."""
    t, e = ecg.r_times_s, ecg.ectopic
    out: list[float] = []
    for i in range(len(t) - 1):
        around = e[max(0, i - 1) : i + 2]
        if not any(around):
            out.append(t[i + 1] - t[i])
    return out


def _signal(ecg: SynthEcg, window_s: float) -> SignalInput:
    n = len(ecg.samples)
    return SignalInput(ecg.fs, window_s, ecg.samples, (True,) * n)


# --- R peaks ---------------------------------------------------------------------------


def test_r_peaks_clean_signal_scores_near_perfect() -> None:
    ecg = synth_ecg(duration_s=90, seed=1)
    beats = detect_beats(ecg.samples, (True,) * len(ecg.samples), ecg.fs)
    assert f1_within(ecg.r_times_s, beats.times_s) >= 0.99


def test_r_peaks_survive_noise_and_wander() -> None:
    ecg = synth_ecg(duration_s=90, noise_sd_mv=0.08, wander_mv=0.3, seed=2)
    beats = detect_beats(ecg.samples, (True,) * len(ecg.samples), ecg.fs)
    assert f1_within(ecg.r_times_s, beats.times_s) >= 0.97


def test_no_beat_is_reported_inside_a_gap_and_no_interval_spans_it() -> None:
    ecg = synth_ecg(duration_s=60, seed=3)
    lo, hi = 20 * 250, 30 * 250
    samples = tuple(float("nan") if lo <= i < hi else x for i, x in enumerate(ecg.samples))
    usable = tuple(not (lo <= i < hi) for i in range(len(samples)))
    beats = detect_beats(samples, usable, ecg.fs)
    assert beats.times_s, "beats are expected outside the gap"
    assert not any(20.0 <= t < 30.0 for t in beats.times_s)
    assert len(set(beats.run)) == 2  # one run before the gap, one after
    nn, _, _ = nn_intervals(beats)
    first_after = next(i for i, r in enumerate(beats.run) if r == 1)
    assert math.isnan(nn[first_after - 1]), "the interval across the gap must be excluded"


def test_unusable_samples_are_ignored_even_when_they_are_finite() -> None:
    # real gaps are often finite garbage under usable=False (samples that failed SQI), so the
    # mask alone has to hide them: here the "gap" holds 5 mV spikes at beat-like spacing
    ecg = synth_ecg(duration_s=60, seed=11)
    lo, hi = 20 * 250, 30 * 250
    samples = list(ecg.samples)
    for i in range(lo, hi, 200):
        samples[i] = 5.0
    usable = tuple(not (lo <= i < hi) for i in range(len(samples)))
    beats = detect_beats(samples, usable, ecg.fs)
    assert any(t < 20.0 for t in beats.times_s)
    assert any(t >= 30.0 for t in beats.times_s)
    assert not any(20.0 <= t < 30.0 for t in beats.times_s)


def test_no_interval_spans_a_short_gap_even_when_it_would_look_normal() -> None:
    # a 0.6 s gap that swallows no beat: the two beats around it are both good and the
    # interval between them is a plausible 1.3 s, so only the run boundary can exclude it
    ecg = synth_ecg(duration_s=60, hr_bpm=45, rr_sd_s=0.01, seed=12)
    k = next(i for i, t in enumerate(ecg.r_times_s) if t > 25.0)
    t_k = ecg.r_times_s[k]
    lo, hi = round((t_k + 0.42) * 250), round((t_k + 1.02) * 250)
    assert ecg.r_times_s[k + 1] > hi / 250 + 0.25  # the next beat survives with a full window
    samples = tuple(float("nan") if lo <= i < hi else x for i, x in enumerate(ecg.samples))
    usable = tuple(not (lo <= i < hi) for i in range(len(samples)))
    beats = detect_beats(samples, usable, ecg.fs)
    i = min(range(len(beats.times_s)), key=lambda j: abs(beats.times_s[j] - t_k))
    assert beats.valid[i]
    assert beats.valid[i + 1]
    assert beats.run[i] != beats.run[i + 1]
    nn, _, _ = nn_intervals(beats)
    assert math.isnan(nn[i])


def test_a_notched_qrs_counts_as_one_beat() -> None:
    ecg = synth_ecg(duration_s=60, seed=14)
    axis = np.arange(len(ecg.samples)) / ecg.fs
    x = np.asarray(ecg.samples)
    for tb in ecg.r_times_s:  # a second spike 0.18 s later, inside the 0.25 s refractory period
        x = x + 0.6 * np.exp(-0.5 * ((axis - (tb + 0.18)) / 0.012) ** 2)
    beats = detect_beats(tuple(float(v) for v in x), (True,) * len(x), ecg.fs)
    assert len(beats.times_s) <= len(ecg.r_times_s)
    assert f1_within(ecg.r_times_s, beats.times_s) >= 0.97


def test_beats_that_do_not_match_the_template_are_flagged_and_left_out_of_hrv() -> None:
    ecg = synth_ecg(duration_s=60, rr_sd_s=0.03, seed=13)
    lo, hi = 40 * 250, 52 * 250  # twelve seconds of polarity-inverted complexes
    samples = tuple(-x if lo <= i < hi else x for i, x in enumerate(ecg.samples))
    beats = detect_beats(samples, (True,) * len(samples), ecg.fs)
    pairs = list(zip(beats.times_s, beats.valid, strict=True))
    inside = [v for t, v in pairs if 40.5 <= t < 51.5]
    clean = [v for t, v in pairs if t < 39.5 or t > 52.5]
    assert len(inside) >= 10
    assert not any(inside)
    assert sum(clean) / len(clean) > 0.9
    nn, _, _ = nn_intervals(beats)
    bad_pairs = [i for i in range(len(nn)) if 40.5 <= beats.times_s[i] < 51.0]
    assert all(math.isnan(nn[i]) for i in bad_pairs)


# --- HRV -------------------------------------------------------------------------------


def test_hrv_matches_truth_on_a_clean_window() -> None:
    ecg = synth_ecg(duration_s=60, rr_sd_s=0.04, seed=4)
    got = hrv_window(ecg.samples, (True,) * len(ecg.samples), ecg.fs)
    assert isinstance(got, HrvValue)
    truth = _rmssd_ms(_truth_nn(ecg))
    assert got.rmssd_ms == pytest.approx(truth, rel=0.10)
    assert got.mean_hr_bpm == pytest.approx(70.0, rel=0.05)
    assert got.nn_coverage > 0.9


def test_premature_beats_are_excluded_and_counted_not_averaged_in() -> None:
    ecg = synth_ecg(duration_s=90, rr_sd_s=0.03, pvc_after_s=(20.0, 50.0), seed=5)
    got = hrv_window(ecg.samples, (True,) * len(ecg.samples), ecg.fs)
    assert isinstance(got, HrvValue)
    assert got.n_excluded >= 4  # a short and a long interval per premature beat, at least
    assert got.rmssd_ms == pytest.approx(_rmssd_ms(_truth_nn(ecg)), rel=0.15)


def test_irregular_rhythm_is_refused_with_a_reason() -> None:
    ecg = synth_ecg(duration_s=90, irregular=True, seed=6)
    got = hrv_window(ecg.samples, (True,) * len(ecg.samples), ecg.fs)
    assert got == NotComputed("irregular_rhythm")


def test_a_long_gap_refuses_the_window() -> None:
    ecg = synth_ecg(duration_s=90, seed=7)
    lo, hi = 10 * 250, 40 * 250  # a 30 s dropout
    samples = tuple(float("nan") if lo <= i < hi else x for i, x in enumerate(ecg.samples))
    usable = tuple(not (lo <= i < hi) for i in range(len(samples)))
    assert hrv_window(samples, usable, ecg.fs) == NotComputed("gap_longer_than_20s")


def test_hrv_never_imputes_across_a_gap() -> None:
    ecg = synth_ecg(duration_s=180, seed=8)
    signal = _signal(ecg, window_s=60.0)  # three 60 s windows
    # drop the whole middle window; outer windows must be untouched
    assert_no_imputation(lambda s: compute_hrv(s, PROV), signal, (60 * 250, 120 * 250))


def test_partly_gapped_window_is_degraded_and_reports_its_coverage() -> None:
    ecg = synth_ecg(duration_s=60, seed=9)
    lo, hi = 5 * 250, 15 * 250  # 10 s of a 60 s window: 83% coverage, gap under 20 s
    samples = tuple(float("nan") if lo <= i < hi else x for i, x in enumerate(ecg.samples))
    valid = tuple(not (lo <= i < hi) for i in range(len(samples)))
    signal = SignalInput(ecg.fs, 60.0, samples, valid)
    (result,) = compute_hrv(signal, PROV)
    assert isinstance(result, Computed)
    assert result.quality.value == "degraded"
    assert result.window.coverage == pytest.approx(1 - 10 / 60, abs=0.01)


# --- burden and baseline ---------------------------------------------------------------


def test_burden_counts_only_valid_minutes_and_reports_coverage() -> None:
    hr = [80.0] * 60 + [120.0] * 30 + [float("nan")] * 30
    usable = [True] * 90 + [False] * 30
    got = hr_burden(hr, usable)
    assert not isinstance(got, NotComputed)
    assert got.minutes_over == 30
    assert got.valid_minutes == 90
    assert got.burden == pytest.approx(30 / 90)
    assert got.coverage == pytest.approx(90 / 120)


def test_unusable_minutes_stay_out_of_numerator_and_denominator_even_when_finite() -> None:
    hr = [80.0] * 60 + [130.0] * 40 + [80.0] * 20  # the 130s were flagged unusable
    usable = [True] * 60 + [False] * 40 + [True] * 20
    got = hr_burden(hr, usable)
    assert not isinstance(got, NotComputed)
    assert got.minutes_over == 0
    assert got.valid_minutes == 80
    assert got.burden == 0.0
    assert got.coverage == pytest.approx(80 / 120)


def test_burden_refuses_when_coverage_is_too_low() -> None:
    hr = [130.0] * 10 + [float("nan")] * 90
    usable = [True] * 10 + [False] * 90
    assert hr_burden(hr, usable) == NotComputed("coverage_below_minimum")


def test_a_gap_is_not_normal_burden_ignores_missing_minutes() -> None:
    # all valid minutes are high; half the series is missing: burden is 1.0, not 0.5
    got = hr_burden([120.0] * 50 + [float("nan")] * 50, [True] * 50 + [False] * 50)
    assert not isinstance(got, NotComputed)
    assert got.burden == 1.0


def test_baseline_is_robust_and_needs_enough_valid_minutes() -> None:
    values = [70.0 + (i % 5) for i in range(120)] + [200.0]  # one wild outlier
    base = robust_baseline(values, [True] * len(values))
    assert isinstance(base, Baseline)
    assert base.median == pytest.approx(72.0, abs=0.5)
    assert base.n == 121
    assert robust_baseline(values[:20], [True] * 20) == NotComputed("baseline_not_established")
    gappy = robust_baseline(values, [i % 2 == 0 for i in range(len(values))], min_valid=100)
    assert gappy == NotComputed("baseline_not_established")


def test_baseline_only_looks_at_the_recent_horizon() -> None:
    old, recent = [50.0] * 200, [90.0] * 100
    base = robust_baseline(old + recent, [True] * 300, horizon=100, min_valid=60)
    assert isinstance(base, Baseline)
    assert base.median == 90.0


def test_robust_z_refuses_a_flat_baseline_and_non_finite_values() -> None:
    flat = Baseline(median=70.0, mad=0.0, n=100)
    assert robust_z(80.0, flat) == NotComputed("baseline_has_no_spread")
    spread = Baseline(median=70.0, mad=2.0, n=100)
    assert robust_z(float("nan"), spread) == NotComputed("value_not_finite")
    z = robust_z(79.0, spread)
    assert isinstance(z, float)
    assert z == pytest.approx(9.0 / (2.0 * 1.4826))


# --- what the mask hides, and what the run edges and minimum run lengths decide ----------


def _masked_with_spikes(
    ecg: SynthEcg, lo_s: float, hi_s: float
) -> tuple[list[float], tuple[bool, ...]]:
    """The ECG with [lo_s, hi_s) unusable but holding finite 5 mV spikes every 0.2 s."""
    lo, hi = round(lo_s * ecg.fs), round(hi_s * ecg.fs)
    samples = list(ecg.samples)
    for i in range(lo, hi, round(0.2 * ecg.fs)):
        samples[i] = 5.0
    return samples, tuple(not (lo <= i < hi) for i in range(len(samples)))


def test_the_gap_rule_sees_a_masked_span_that_holds_finite_values() -> None:
    # 120 s window: beats elsewhere keep NN coverage above 75%, so only the 20 s gap rule can
    # refuse it. A rule that read only isfinite would call the finite spikes signal.
    ecg = synth_ecg(duration_s=120, seed=41)
    samples, usable = _masked_with_spikes(ecg, 40.0, 61.0)  # 21 s
    assert hrv_window(samples, usable, ecg.fs) == NotComputed("gap_longer_than_20s")


def test_a_masked_span_just_under_the_gap_limit_is_computed_and_not_moved_by_its_contents() -> None:
    ecg = synth_ecg(duration_s=120, seed=41)
    spiked, usable = _masked_with_spikes(ecg, 40.0, 59.0)  # 19 s
    lo, hi = round(40.0 * ecg.fs), round(59.0 * ecg.fs)
    blank = [float("nan") if lo <= i < hi else x for i, x in enumerate(ecg.samples)]
    got = hrv_window(spiked, usable, ecg.fs)
    assert isinstance(got, HrvValue)
    assert got == hrv_window(blank, usable, ecg.fs)


def test_beats_too_close_to_a_run_edge_are_invalid_and_leave_the_intervals() -> None:
    # crop a clean recording so the first R peak is 0.1 s after the start (inside the 0.2 s
    # pre-window) and the last 0.2 s before the end (inside the 0.4 s post-window)
    ecg = synth_ecg(duration_s=40, seed=42)
    first, last = ecg.r_times_s[3], ecg.r_times_s[-4]
    lo, hi = round((first - 0.1) * ecg.fs), round((last + 0.2) * ecg.fs)
    crop = ecg.samples[lo:hi]
    beats = detect_beats(crop, (True,) * len(crop), ecg.fs)
    assert beats.times_s[0] == pytest.approx(0.1, abs=0.03)
    assert beats.times_s[-1] == pytest.approx(len(crop) / ecg.fs - 0.2, abs=0.03)
    assert beats.valid[0] is False
    assert beats.valid[-1] is False
    assert all(beats.valid[1:-1])  # the interior beats are scored normally
    nn, _, _ = nn_intervals(beats)
    assert np.isnan(nn[0])  # the pairs touching an edge beat are excluded
    assert np.isnan(nn[-1])
    assert np.isfinite(nn[1:-1]).sum() >= len(nn) - 4


@pytest.mark.parametrize(
    "gains", [(3.0, 1.0), (1.0, 3.0)], ids=["loud-then-quiet", "quiet-then-loud"]
)
def test_each_usable_run_sets_its_own_qrs_threshold(gains: tuple[float, float]) -> None:
    # a gain change after a gap: the quiet run has 1/9 of the QRS slope energy, below the
    # threshold fraction of the loud run's, so a threshold shared across runs misses it
    a = synth_ecg(duration_s=30, seed=51)
    b = synth_ecg(duration_s=30, seed=52)
    gap = round(5 * a.fs)
    samples = (
        [gains[0] * x for x in a.samples] + [float("nan")] * gap + [gains[1] * x for x in b.samples]
    )
    usable = (True,) * len(a.samples) + (False,) * gap + (True,) * len(b.samples)
    beats = detect_beats(samples, usable, a.fs)
    offset = 30.0 + gap / a.fs
    found_a = tuple(t for t in beats.times_s if t < 30.0)
    found_b = tuple(t for t in beats.times_s if t >= offset)
    assert f1_within(a.r_times_s, found_a) > 0.95
    assert f1_within(tuple(offset + t for t in b.r_times_s), found_b) > 0.95


def test_a_usable_run_shorter_than_the_minimum_is_not_searched_for_beats() -> None:
    ecg = synth_ecg(duration_s=60, seed=43)
    fs = ecg.fs

    def only(lo_s: float, hi_s: float) -> tuple[bool, ...]:
        return tuple(lo_s * fs <= i < hi_s * fs for i in range(len(ecg.samples)))

    assert detect_beats(ecg.samples, only(20.0, 22.5), fs).times_s == ()  # 2.5 s < 3 s
    assert len(detect_beats(ecg.samples, only(20.0, 24.0), fs).times_s) >= 3  # 4 s


# --- the numbers the card promises: minimum runs, templates, HRV refusals ---------------


def test_a_usable_run_of_exactly_the_minimum_is_searched_and_one_sample_less_is_not() -> None:
    ecg = synth_ecg(duration_s=60, seed=43)
    fs = ecg.fs

    def only(lo_s: float, hi_s: float) -> tuple[bool, ...]:
        return tuple(lo_s * fs <= i < hi_s * fs for i in range(len(ecg.samples)))

    assert len(detect_beats(ecg.samples, only(20.0, 23.0), fs).times_s) >= 2  # 750 samples
    assert detect_beats(ecg.samples, only(20.0, 23.0 - 1 / fs), fs).times_s == ()  # 749


@pytest.mark.parametrize(
    ("hr_bpm", "crop_s", "expected_beats", "all_valid"),
    [(40.0, 3.0, 2, False), (60.0, 3.4, 3, True)],
    ids=["two-scorable-beats", "three-scorable-beats"],
)
def test_a_template_needs_three_scorable_beats(
    hr_bpm: float, crop_s: float, expected_beats: int, all_valid: bool
) -> None:
    ecg = synth_ecg(duration_s=10, hr_bpm=hr_bpm, rr_sd_s=0.0, seed=45)
    crop = ecg.samples[: round(crop_s * ecg.fs)]
    beats = detect_beats(crop, (True,) * len(crop), ecg.fs)
    assert len(beats.times_s) == expected_beats
    assert all(beats.valid) is all_valid
    assert any(beats.valid) is all_valid  # with two beats none is judged, never some


def test_a_masked_span_of_exactly_the_gap_limit_is_computed() -> None:
    ecg = synth_ecg(duration_s=120, seed=41)
    samples, usable = _masked_with_spikes(ecg, 40.0, 60.0)  # 20.0 s, not more than the limit
    assert isinstance(hrv_window(samples, usable, ecg.fs), HrvValue)


def test_too_little_valid_signal_for_sdnn_is_refused_with_its_reason() -> None:
    ecg = synth_ecg(duration_s=20, seed=44)  # every interval valid, but under 30 s of them
    got = hrv_window(ecg.samples, (True,) * len(ecg.samples), ecg.fs)
    assert got == NotComputed("insufficient_valid_nn")


def test_scattered_gaps_under_the_limit_can_still_fail_the_coverage_rule() -> None:
    # three 15 s gaps in 120 s: no gap is over 20 s, so only the 75% coverage rule can refuse
    ecg = synth_ecg(duration_s=120, seed=46)
    spans = [(10.0, 25.0), (45.0, 60.0), (80.0, 95.0)]
    usable = tuple(
        not any(lo * ecg.fs <= i < hi * ecg.fs for lo, hi in spans) for i in range(len(ecg.samples))
    )
    samples = [x if ok else float("nan") for x, ok in zip(ecg.samples, usable, strict=True)]
    assert hrv_window(samples, usable, ecg.fs) == NotComputed("nn_coverage_below_75pct")


def test_burden_and_baseline_reject_series_of_different_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        hr_burden([80.0, 90.0], [True])
    with pytest.raises(ValueError, match="same length"):
        robust_baseline([1.0, 2.0], [True])


def test_a_minute_exactly_at_the_burden_threshold_counts() -> None:
    got = hr_burden([HR_BURDEN_BPM] * 60, [True] * 60)
    assert not isinstance(got, NotComputed)
    assert got.minutes_over == 60


def test_a_baseline_needs_exactly_the_minimum_valid_minutes() -> None:
    n = BASELINE_MIN_VALID
    assert isinstance(robust_baseline([70.0] * n, [True] * n), Baseline)
    assert robust_baseline([70.0] * (n - 1), [True] * (n - 1)) == NotComputed(
        "baseline_not_established"
    )


def test_an_empty_series_is_refused_as_no_minutes_not_as_low_coverage() -> None:
    assert hr_burden([], []) == NotComputed("no_minutes")


# --- edges and ties the detector decides at the exact sample -------------------------------


def _spikes(
    duration_s: float, fs: float, times: list[float], amps: list[float]
) -> tuple[float, ...]:
    """A flat trace with a narrow QRS-like spike at each time: exact, noise-free beat times."""
    t = np.arange(round(duration_s * fs)) / fs
    x = np.zeros_like(t)
    for tb, amp in zip(times, amps, strict=True):
        x += amp * np.exp(-0.5 * ((t - tb) / 0.012) ** 2)
    return tuple(float(v) for v in x)


@pytest.mark.parametrize(("samples_apart", "beats"), [(62, 5), (61, 4)], ids=["62", "61"])
def test_two_r_peaks_one_refractory_apart_are_two_beats_and_one_sample_closer_are_one(
    samples_apart: int, beats: int
) -> None:
    fs = 250.0  # the refractory is round(0.25 s * fs) = 62 samples
    x = _spikes(5.0, fs, [0.6, 1.6, 2.6, 3.6, 3.6 + samples_apart / fs], [1.0] * 5)
    assert len(detect_beats(x, (True,) * len(x), fs).times_s) == beats


@pytest.mark.parametrize(
    ("first", "second", "kept_s"), [(0.6, 1.0, 3.57), (1.0, 0.6, 3.4)], ids=["later", "earlier"]
)
def test_two_candidates_inside_the_refractory_keep_the_larger_peak(
    first: float, second: float, kept_s: float
) -> None:
    fs = 250.0
    x = _spikes(5.0, fs, [0.6, 1.6, 2.6, 3.4, 3.57], [1.0, 1.0, 1.0, first, second])
    beats = detect_beats(x, (True,) * len(x), fs)
    assert len(beats.times_s) == 4
    assert beats.times_s[-1] == pytest.approx(kept_s, abs=0.01)


def test_a_beat_exactly_a_window_from_the_run_edge_is_scored_and_one_sample_closer_is_not() -> None:
    fs = 250.0  # pre-window 0.2 s = 50 samples, post-window 0.4 s = 100 samples
    at_limit = _spikes(4.6, fs, [0.2, 1.2, 2.2, 3.2, 4.2], [1.0] * 5)
    got = detect_beats(at_limit, (True,) * len(at_limit), fs)
    assert got.valid == (True, True, True, True, False)  # the last needs one more sample
    inside = _spikes(4.6, fs, [0.196, 1.2, 2.2, 3.2, 4.196], [1.0] * 5)
    got = detect_beats(inside, (True,) * len(inside), fs)
    assert got.valid == (False, True, True, True, True)  # the first is one sample too close


def test_one_pair_of_beats_gives_one_interval() -> None:
    nn, ectopic, plausible = nn_intervals(Beats((1.0, 2.0), (True, True), (0, 0), (1.0, 1.0)))
    assert nn.tolist() == [1.0]
    assert (ectopic, plausible) == (0, 1)


def test_an_interval_with_exactly_three_neighbours_is_still_judged_for_ectopy() -> None:
    beats = Beats((0.0, 1.0, 2.0, 3.0, 3.5), (True,) * 5, (0,) * 5, (1.0,) * 5)
    nn, ectopic, _ = nn_intervals(beats)
    assert np.isnan(nn[-1])
    assert ectopic == 1


def test_a_flat_baseline_is_usable_at_exactly_the_minimum_spread() -> None:
    base = Baseline(median=1.0, mad=1.0, n=100)
    got = robust_z(2.0, base, min_scale=base.scale)
    assert got == pytest.approx(1.0 / base.scale)
