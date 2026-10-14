"""M2b: perfusion index and agreement-gated respiratory rate score against known truth."""

from collections.abc import Sequence

import numpy as np
import pytest
from no_imputation import assert_mask_invariance, assert_no_imputation, with_gap
from synth_vitals import SynthVitals, synth_vitals

from biosentry.domain.computed import Computed, NotComputed, Result
from biosentry.domain.scoring.tier_b.ppg import PiValue, compute_pi, detect_pulses, pi_window
from biosentry.domain.scoring.tier_b.respiration import (
    RrValue,
    agree,
    rr_from_accel,
    rr_from_ecg,
    rr_from_ppg,
    rr_windows,
)
from biosentry.domain.signals import SignalInput
from biosentry.schemas import Provenance
from samples import provenance

PROV = Provenance.model_validate(provenance())
WINDOW_S = 32.0


def _sig(samples: tuple[float, ...], fs: float, window_s: float = WINDOW_S) -> SignalInput:
    return SignalInput(fs, window_s, samples, (True,) * len(samples))


def _gapped(sig: SignalInput, lo_s: float, hi_s: float) -> SignalInput:
    lo, hi = round(lo_s * sig.fs), round(hi_s * sig.fs)
    samples = tuple(float("nan") if lo <= i < hi else x for i, x in enumerate(sig.samples))
    valid = tuple(v and not lo <= i < hi for i, v in enumerate(sig.valid))
    return SignalInput(sig.fs, sig.window_s, samples, valid)


def _channels(v: SynthVitals) -> tuple[SignalInput, SignalInput, SignalInput]:
    return _sig(v.ecg, v.ecg_fs), _sig(v.ppg, v.ppg_fs), _sig(v.accel, v.accel_fs)


# --- perfusion index -------------------------------------------------------------------


def test_perfusion_index_tracks_ac_over_dc() -> None:
    for ac in (12.0, 30.0):
        v = synth_vitals(duration_s=40, ppg_ac=ac, seed=1)
        got = pi_window(v.ppg, (True,) * len(v.ppg), v.ppg_fs)
        assert isinstance(got, PiValue)
        assert got.pi_percent == pytest.approx(v.pi_percent, rel=0.2)
        assert got.valid_share > 0.9


def _spiked(v: SynthVitals, times: list[float], height: float) -> tuple[float, ...]:
    axis = np.arange(len(v.ppg)) / v.ppg_fs
    spikes = np.zeros(len(v.ppg))
    for tb in times:
        spikes += height * np.exp(-0.5 * ((axis - tb) / 0.02) ** 2)
    return tuple(float(a + b) for a, b in zip(v.ppg, spikes, strict=True))


def test_template_failing_pulses_do_not_enter_the_perfusion_index() -> None:
    # usable but wrong-shaped events (a few narrow 3x spikes between pulses) are detected as
    # peaks; they must be flagged invalid and left out of both the median and the count
    v = synth_vitals(duration_s=40, ppg_ac=12.0, seed=19)
    clean = pi_window(v.ppg, (True,) * len(v.ppg), v.ppg_fs)
    assert isinstance(clean, PiValue)
    noisy = _spiked(v, [5.3, 11.9, 18.4, 24.1, 30.2, 35.6], 3 * 12.0)
    got = pi_window(noisy, (True,) * len(noisy), v.ppg_fs)
    assert isinstance(got, PiValue)
    assert got.pi_percent == pytest.approx(clean.pi_percent, rel=0.1)
    assert got.n_pulses <= clean.n_pulses
    assert got.valid_share < clean.valid_share  # the spikes are visible as rejected pulses


def test_a_periodic_artefact_bigger_than_the_pulse_is_caught_by_the_ecg_rate_check() -> None:
    # steady-cadence artefact at ~37/min, 8x the pulse: it takes over detection, so the PPG
    # alone cannot tell; the ECG rate (72/min) can
    v = synth_vitals(duration_s=40, hr_bpm=72.0, ppg_ac=12.0, seed=21)
    noisy = _spiked(v, [float(x) for x in np.arange(3.1, 36.0, 1.6)], 8 * 12.0)
    usable = (True,) * len(noisy)
    alone = pi_window(noisy, usable, v.ppg_fs)
    assert isinstance(alone, PiValue)
    assert alone.pulse_rate_bpm == pytest.approx(37.5, abs=3.0)  # visible to the caller
    checked = pi_window(noisy, usable, v.ppg_fs, expected_hr_bpm=72.0)
    assert checked == NotComputed("pulse_rate_disagrees_with_ecg")
    honest = pi_window(v.ppg, (True,) * len(v.ppg), v.ppg_fs, expected_hr_bpm=72.0)
    assert isinstance(honest, PiValue)
    assert honest.pulse_rate_bpm == pytest.approx(72.0, abs=3.0)


def test_a_negative_dc_level_is_refused_not_reported() -> None:
    v = synth_vitals(duration_s=40, ppg_dc=-500.0, ppg_ac=12.0, seed=20)
    assert pi_window(v.ppg, (True,) * len(v.ppg), v.ppg_fs) == NotComputed("dc_not_positive")


def test_pulses_are_not_reported_inside_a_gap() -> None:
    v = synth_vitals(duration_s=60, seed=2)
    sig = _gapped(_sig(v.ppg, v.ppg_fs, 60.0), 20.0, 35.0)
    pulses = detect_pulses(sig.samples, sig.usable, sig.fs)
    assert pulses.times_s
    assert not any(20.0 <= t < 35.0 for t in pulses.times_s)
    assert len(set(pulses.run)) == 2


def test_perfusion_index_is_refused_when_too_little_signal_remains() -> None:
    v = synth_vitals(duration_s=40, seed=3)
    sig = _gapped(_sig(v.ppg, v.ppg_fs, 40.0), 4.0, 38.0)
    assert pi_window(sig.samples, sig.usable, sig.fs) == NotComputed("too_few_valid_pulses")


def test_perfusion_index_windows_carry_coverage_and_never_fill() -> None:
    v = synth_vitals(duration_s=64, seed=4)
    sig = _gapped(_sig(v.ppg, v.ppg_fs), 36.0, 44.0)  # 8 s of the second 32 s window
    first, second = compute_pi(sig, PROV)
    assert isinstance(first, Computed)
    assert first.quality.value == "ok"
    assert isinstance(second, Computed)
    assert second.quality.value == "degraded"
    assert second.window.coverage == pytest.approx(0.75, abs=0.01)


# --- respiratory rate ------------------------------------------------------------------


@pytest.mark.parametrize("rr", [12.0, 18.0, 24.0])
def test_each_estimator_recovers_the_rate(rr: float) -> None:
    v = synth_vitals(duration_s=WINDOW_S, rr_bpm=rr, seed=5)
    ecg, ppg, accel = _channels(v)
    for name, got in (
        ("ecg", rr_from_ecg(ecg.samples, ecg.usable, ecg.fs)),
        ("ppg", rr_from_ppg(ppg.samples, ppg.usable, ppg.fs)),
        ("accel", rr_from_accel(accel.samples, accel.usable, accel.fs)),
    ):
        assert got is not None, name
        assert got == pytest.approx(rr, abs=2.0), name


def test_gated_rate_averages_the_agreeing_estimators() -> None:
    v = synth_vitals(duration_s=WINDOW_S, rr_bpm=15.0, seed=6)
    ecg, ppg, accel = _channels(v)
    (got,) = rr_windows(ecg, ppg, accel, PROV)
    assert isinstance(got, Computed)
    assert isinstance(got.value, RrValue)
    assert got.value.breaths_per_min == pytest.approx(15.0, abs=2.0)
    assert got.value.estimators == ("accel", "ecg", "ppg")
    assert got.quality.value == "ok"


def test_a_dissenting_estimator_is_outvoted_and_named() -> None:
    v = synth_vitals(duration_s=WINDOW_S, rr_bpm=15.0, accel_rr_bpm=27.0, seed=7)
    ecg, ppg, accel = _channels(v)
    (got,) = rr_windows(ecg, ppg, accel, PROV)
    assert isinstance(got, Computed)
    assert got.value.estimators == ("ecg", "ppg")
    assert got.value.n_available == 3
    assert got.value.breaths_per_min == pytest.approx(15.0, abs=2.0)


def test_three_way_disagreement_is_refused_not_averaged() -> None:
    v = synth_vitals(
        duration_s=WINDOW_S,
        rr_bpm=15.0,
        ecg_rr_bpm=11.0,
        ppg_rr_bpm=19.0,
        accel_rr_bpm=27.0,
        seed=8,
    )
    ecg, ppg, accel = _channels(v)
    assert rr_windows(ecg, ppg, accel, PROV) == (NotComputed("estimators_disagree"),)


def test_one_estimator_is_not_enough() -> None:
    v = synth_vitals(duration_s=WINDOW_S, seed=9)
    ecg, _, _ = _channels(v)
    assert rr_windows(ecg, None, None, PROV) == (NotComputed("insufficient_estimators"),)


def _white(rng: np.random.Generator, fs: float) -> tuple[float, ...]:
    return tuple(float(x) for x in rng.normal(0.0, 1.0, round(fs * WINDOW_S)))


def test_noise_alone_never_produces_a_rate() -> None:
    for seed in range(12):
        rng = np.random.default_rng(seed)
        ecg = _sig(_white(rng, 250.0), 250.0)
        ppg = _sig(tuple(1000.0 + x for x in _white(rng, 100.0)), 100.0)
        accel = _sig(_white(rng, 25.0), 25.0)
        (got,) = rr_windows(ecg, ppg, accel, PROV)
        assert isinstance(got, NotComputed), f"seed {seed} produced {got!r}"


def test_a_gap_over_a_whole_window_yields_nothing_and_leaves_other_windows_alone() -> None:
    v = synth_vitals(duration_s=96, rr_bpm=15.0, seed=10)
    ecg, ppg, accel = _channels(v)
    clean = rr_windows(ecg, ppg, accel, PROV)
    assert len(clean) == 3
    assert all(isinstance(r, Computed) for r in clean)
    gapped = rr_windows(
        _gapped(ecg, 32.0, 64.0), _gapped(ppg, 32.0, 64.0), _gapped(accel, 32.0, 64.0), PROV
    )
    assert gapped[0] == clean[0]
    assert isinstance(gapped[1], NotComputed)
    assert gapped[2] == clean[2]


def test_window_coverage_is_that_of_the_least_covered_voter() -> None:
    v = synth_vitals(duration_s=WINDOW_S, rr_bpm=15.0, seed=15)
    ecg, ppg, accel = _channels(v)
    (got,) = rr_windows(_gapped(ecg, 4.0, 12.0), ppg, accel, PROV)  # a quarter of the ECG missing
    assert isinstance(got, Computed)
    assert got.window.coverage == pytest.approx(0.75, abs=0.01)
    assert got.quality.value == "degraded"


def test_a_channel_below_the_coverage_floor_does_not_vote() -> None:
    # a quarter of the ECG is missing (75% coverage) and what is left carries a different
    # rate: at a 0.8 floor it must not vote, at the default it votes and is outvoted
    v = synth_vitals(duration_s=WINDOW_S, rr_bpm=15.0, ecg_rr_bpm=27.0, seed=16)
    ecg, ppg, accel = _channels(v)
    thin = _gapped(ecg, 4.0, 12.0)
    assert rr_from_ecg(thin.samples, thin.usable, thin.fs) is not None  # it could have voted
    (floor,) = rr_windows(thin, ppg, accel, PROV, min_coverage=0.8)
    assert isinstance(floor, Computed)
    assert floor.value.n_available == 2
    assert floor.value.estimators == ("accel", "ppg")
    (default,) = rr_windows(thin, ppg, accel, PROV)
    assert isinstance(default, Computed)
    assert default.value.n_available == 3
    assert default.value.estimators == ("accel", "ppg")


def test_unmasked_garbage_in_a_ppg_gap_is_ignored() -> None:
    v = synth_vitals(duration_s=60, seed=17)
    samples = list(v.ppg)
    lo, hi = round(20 * v.ppg_fs), round(35 * v.ppg_fs)
    for i in range(lo, hi, round(0.8 * v.ppg_fs)):  # finite spikes at pulse-like spacing
        samples[i] = 5000.0
    usable = tuple(not (lo <= i < hi) for i in range(len(samples)))
    pulses = detect_pulses(samples, usable, v.ppg_fs)
    assert any(t < 20.0 for t in pulses.times_s)
    assert not any(20.0 <= t < 35.0 for t in pulses.times_s)


def test_beat_channels_without_breathing_modulation_do_not_vote() -> None:
    for seed in range(8):
        v = synth_vitals(
            duration_s=WINDOW_S, rr_bpm=15.0, depth=0.0, ppg_baseline=0.0, noise=0.5, seed=seed
        )
        ecg, ppg, accel = _channels(v)
        (got,) = rr_windows(ecg, ppg, accel, PROV)
        assert got == NotComputed("insufficient_estimators"), f"seed {seed}: {got!r}"


def test_an_accelerometer_with_no_breathing_motion_does_not_vote() -> None:
    v = synth_vitals(duration_s=WINDOW_S, rr_bpm=15.0, accel_amp=0.0, seed=18)
    ecg, ppg, accel = _channels(v)
    (got,) = rr_windows(ecg, ppg, accel, PROV)
    assert isinstance(got, Computed)
    assert got.value.n_available == 2
    assert got.value.estimators == ("ecg", "ppg")


def test_agreement_picks_the_largest_group_within_tolerance() -> None:
    got = agree({"ecg": 14.0, "ppg": 15.5, "accel": 24.0})
    assert isinstance(got, RrValue)
    assert got.estimators == ("ecg", "ppg")
    assert got.breaths_per_min == pytest.approx(14.75)
    assert got.spread_bpm == pytest.approx(1.5)
    assert agree({"ecg": 14.0, "ppg": 20.0}) == NotComputed("estimators_disagree")
    assert agree({"ecg": 14.0}) == NotComputed("insufficient_estimators")
    assert agree({}) == NotComputed("insufficient_estimators")


# --- the shared no-imputation and mask-invariance checks -------------------------------
# assert_no_imputation also runs assert_mask_invariance: the same gap with NaN, +1e9 and -1e9
# under the mask, at the given span and shifted by half a window.


def _follow(channel: SignalInput, clean: SignalInput, gapped: SignalInput) -> SignalInput:
    """`channel` with the time spans, and the fill value, that `gapped` masks in `clean`."""
    samples = list(channel.samples)
    valid = list(channel.valid)
    for i in range(len(samples)):
        j = min(len(clean.samples) - 1, int(i * clean.fs / channel.fs))
        if clean.valid[j] and not gapped.valid[j]:
            samples[i] = gapped.samples[j]
            valid[i] = False
    return SignalInput(channel.fs, channel.window_s, tuple(samples), tuple(valid))


def test_perfusion_index_never_imputes_and_the_mask_alone_decides() -> None:
    v = synth_vitals(duration_s=128, seed=31)  # four 32 s windows; the middle two are masked
    ppg = _sig(v.ppg, v.ppg_fs)
    n = ppg.samples_per_window
    assert_no_imputation(lambda s: compute_pi(s, PROV), ppg, (n, 3 * n))


def test_perfusion_index_with_the_ecg_rate_check_also_obeys_the_mask() -> None:
    v = synth_vitals(duration_s=128, hr_bpm=72.0, seed=32)
    ppg = _sig(v.ppg, v.ppg_fs)
    n = ppg.samples_per_window
    assert_no_imputation(lambda s: compute_pi(s, PROV, expected_hr_bpm=72.0), ppg, (n, 3 * n))


def test_respiratory_rate_never_imputes_and_the_mask_alone_decides() -> None:
    # the gap is cut from the ECG and followed on the PPG and accelerometer, so no channel
    # can vote inside it; garbage under the mask must not move any window
    v = synth_vitals(duration_s=128, rr_bpm=15.0, seed=33)
    ecg, ppg, accel = _channels(v)

    def process(s: SignalInput) -> tuple[Result[RrValue], ...]:
        return rr_windows(s, _follow(ppg, ecg, s), _follow(accel, ecg, s), PROV)

    n = ecg.samples_per_window
    assert_no_imputation(process, ecg, (n, 3 * n))


def test_a_channel_that_is_not_masked_keeps_the_window_alive() -> None:
    # control for the check above: mask only the ECG and the PPG and accelerometer still
    # agree, so the window is rightly computed; the masked-everywhere run is what is empty
    v = synth_vitals(duration_s=96, rr_bpm=15.0, seed=34)
    ecg, ppg, accel = _channels(v)
    n = ecg.samples_per_window
    only_ecg = with_gap(ecg, n, 2 * n)
    (_, middle, _) = rr_windows(only_ecg, ppg, accel, PROV)
    assert isinstance(middle, Computed)
    assert middle.value.estimators == ("accel", "ppg")
    everywhere = rr_windows(
        only_ecg, _follow(ppg, ecg, only_ecg), _follow(accel, ecg, only_ecg), PROV
    )
    assert isinstance(everywhere[1], NotComputed)


def test_the_follow_helper_masks_by_time_not_by_index() -> None:
    v = synth_vitals(duration_s=64, seed=35)
    ecg, ppg, _ = _channels(v)
    lo, hi = round(10 * ecg.fs), round(20 * ecg.fs)
    gapped = with_gap(ecg, lo, hi, fill=1e9)
    follow = _follow(ppg, ecg, gapped)
    masked = [i for i, ok in enumerate(follow.valid) if not ok]
    assert masked[0] == round(10 * ppg.fs)
    assert masked[-1] == round(20 * ppg.fs) - 1
    assert all(follow.samples[i] == 1e9 for i in masked)
    assert all(
        follow.samples[i] == ppg.samples[i] for i in range(len(ppg.samples)) if i not in masked
    )


def test_respiratory_rate_ignores_garbage_under_a_short_mask() -> None:
    # 6 s of a 64 s window is masked on every channel and the window is still computed from
    # what is left; a mask-blind accelerometer would read the 1e9 plateau and answer 6 breaths/min
    v = synth_vitals(duration_s=192, rr_bpm=15.0, seed=36)
    ecg = _sig(v.ecg, v.ecg_fs, 64.0)
    ppg = _sig(v.ppg, v.ppg_fs, 64.0)
    accel = _sig(v.accel, v.accel_fs, 64.0)

    def process(s: SignalInput) -> tuple[Result[RrValue], ...]:
        return rr_windows(s, _follow(ppg, ecg, s), _follow(accel, ecg, s), PROV)

    n = ecg.samples_per_window
    gap = (n + round(10 * ecg.fs), n + round(16 * ecg.fs))
    clean = process(with_gap(ecg, *gap))
    assert isinstance(clean[1], Computed)  # the partly masked window still has a rate
    assert clean[1].value.estimators == ("accel", "ecg", "ppg")
    assert clean[1].value.breaths_per_min == pytest.approx(15.0, abs=1.0)
    assert_mask_invariance(process, ecg, gap)


def test_perfusion_index_ignores_garbage_under_a_short_mask() -> None:
    v = synth_vitals(duration_s=96, seed=37)
    ppg = _sig(v.ppg, v.ppg_fs)
    n = ppg.samples_per_window
    gap = (n + round(2 * ppg.fs), n + round(8 * ppg.fs))
    clean = compute_pi(with_gap(ppg, *gap), PROV)
    assert isinstance(clean[1], Computed)
    assert_mask_invariance(lambda s: compute_pi(s, PROV), ppg, gap)


def test_a_usable_run_shorter_than_the_minimum_is_not_searched_for_pulses() -> None:
    v = synth_vitals(duration_s=60, seed=38)
    fs = v.ppg_fs

    def only(lo_s: float, hi_s: float) -> tuple[bool, ...]:
        return tuple(lo_s * fs <= i < hi_s * fs for i in range(len(v.ppg)))

    assert detect_pulses(v.ppg, only(20.0, 24.0), fs).times_s == ()  # 4 s < 5 s
    assert len(detect_pulses(v.ppg, only(20.0, 26.0), fs).times_s) >= 4  # 6 s


def test_a_ppg_run_of_exactly_the_minimum_is_searched_and_one_sample_less_is_not() -> None:
    v = synth_vitals(duration_s=60, seed=38)
    fs = v.ppg_fs

    def only(lo_s: float, hi_s: float) -> tuple[bool, ...]:
        return tuple(lo_s * fs <= i < hi_s * fs for i in range(len(v.ppg)))

    assert len(detect_pulses(v.ppg, only(20.0, 25.0), fs).times_s) >= 3  # 500 samples
    assert detect_pulses(v.ppg, only(20.0, 25.0 - 1 / fs), fs).times_s == ()  # 499


@pytest.mark.parametrize(
    ("lo_s", "hi_s", "valid"),
    [(10.5, 15.5, 2), (11.0, 16.0, 0)],
    ids=["three-scorable-pulses", "two-scorable-pulses"],
)
def test_a_pulse_template_needs_three_scorable_pulses(lo_s: float, hi_s: float, valid: int) -> None:
    # 40 bpm, 5 s runs: the first has three pulses with room for a template (two of them have a
    # full foot and DC window), the second only two, so nothing in it is judged valid
    v = synth_vitals(duration_s=60, hr_bpm=40.0, seed=61)
    usable = tuple(lo_s * v.ppg_fs <= i < hi_s * v.ppg_fs for i in range(len(v.ppg)))
    assert sum(detect_pulses(v.ppg, usable, v.ppg_fs).valid) == valid


def test_too_few_valid_pulses_are_refused_and_enough_are_computed() -> None:
    v = synth_vitals(duration_s=40, seed=62)
    n = len(v.ppg)

    def first(seconds: float) -> tuple[bool, ...]:
        return tuple(i < seconds * v.ppg_fs for i in range(n))

    assert pi_window(v.ppg, first(8.0), v.ppg_fs) == NotComputed("too_few_valid_pulses")
    assert isinstance(pi_window(v.ppg, first(14.0), v.ppg_fs), PiValue)


def test_a_window_where_most_pulses_fail_the_template_is_refused_for_quality() -> None:
    # fourteen 5 s usable runs at 40 bpm, alternately with three pulses (two judged valid) and
    # four (none judged: only two had room for a template): 14 valid of 49 detected
    v = synth_vitals(duration_s=130, hr_bpm=40.0, seed=61)
    starts = (2.5, 8.0, 13.5, 20.0, 25.5, 32.25, 37.75, 44.0, 49.5, 56.0, 61.5, 68.0, 73.5, 80.0)
    usable = tuple(
        any(lo * v.ppg_fs <= i < (lo + 5.0) * v.ppg_fs for lo in starts) for i in range(len(v.ppg))
    )
    pulses = detect_pulses(v.ppg, usable, v.ppg_fs)
    assert sum(pulses.valid) >= 10  # enough valid pulses, so the share is what refuses it
    assert sum(pulses.valid) / len(pulses.valid) < 0.5
    assert pi_window(v.ppg, usable, v.ppg_fs) == NotComputed("low_signal_quality")


def test_agreement_is_inclusive_at_the_tolerance() -> None:
    assert isinstance(agree({"ecg": 12.0, "ppg": 15.0}), RrValue)
    assert agree({"ecg": 12.0, "ppg": 15.01}) == NotComputed("estimators_disagree")


def test_channels_must_share_the_window_length() -> None:
    v = synth_vitals(duration_s=64, seed=63)
    ecg, ppg, _ = _channels(v)
    short = SignalInput(ppg.fs, WINDOW_S / 2, ppg.samples, ppg.valid)
    with pytest.raises(ValueError, match="must share window_s"):
        rr_windows(ecg, short, None, PROV)


def test_a_channel_exactly_at_the_coverage_floor_still_votes() -> None:
    # 8 s of the first 32 s window masked on every channel: coverage is exactly 0.75, the floor
    v = synth_vitals(duration_s=64, rr_bpm=15.0, seed=30)
    ecg, ppg, accel = (_gapped(c, 0.0, 8.0) for c in _channels(v))
    (first, _) = rr_windows(ecg, ppg, accel, PROV, min_coverage=0.75)
    assert isinstance(first, Computed)
    assert first.window.coverage == pytest.approx(0.75)
    assert first.value.estimators == ("ecg", "ppg")
    just_above = rr_windows(ecg, ppg, accel, PROV, min_coverage=0.76)
    assert just_above[0] == NotComputed("insufficient_estimators")


def _bumps(
    duration_s: float,
    fs: float,
    times: list[float],
    extra: Sequence[tuple[float, float, float]] = (),
    sigma_s: float = 0.09,
) -> tuple[float, ...]:
    """DC 1000 plus a Gaussian pulse (AC 12) at each time, and optional (time, amp, sigma) bumps."""
    t = np.arange(round(duration_s * fs)) / fs
    x = np.full_like(t, 1000.0)
    for tb in times:
        x += 12.0 * np.exp(-0.5 * ((t - tb) / sigma_s) ** 2)
    for tb, amp, sigma in extra:
        x += amp * np.exp(-0.5 * ((t - tb) / sigma) ** 2)
    return tuple(float(v) for v in x)


def test_a_pulse_exactly_a_second_from_the_run_edge_is_scored_and_one_sample_closer_is_not() -> (
    None
):
    fs = 100.0  # the foot and DC windows need 1 s (100 samples) on each side
    at_limit = _bumps(6.0, fs, [1.0, 2.0, 3.0, 4.0, 5.0])
    got = detect_pulses(at_limit, (True,) * len(at_limit), fs)
    assert got.valid == (True, True, True, True, False)  # p + 1 s is the run end
    inside = _bumps(6.0, fs, [0.99, 2.0, 3.0, 4.0, 4.99])
    got = detect_pulses(inside, (True,) * len(inside), fs)
    assert got.valid == (False, True, True, True, True)  # the first is one sample too close


def test_a_second_peak_inside_the_refractory_is_one_pulse_and_the_taller_one_is_kept() -> None:
    fs = 100.0
    beats = [0.8 + k for k in range(12)]
    smaller = _bumps(14.0, fs, beats, [(b + 0.2, 0.8 * 12.0, 0.04) for b in beats])
    taller = _bumps(14.0, fs, beats, [(b + 0.2, 1.3 * 12.0, 0.04) for b in beats])
    first = detect_pulses(smaller, (True,) * len(smaller), fs)
    assert len(first.times_s) == 12
    assert first.times_s[3] == pytest.approx(3.8, abs=0.03)
    second = detect_pulses(taller, (True,) * len(taller), fs)
    assert len(second.times_s) == 12
    assert second.times_s[3] == pytest.approx(3.99, abs=0.03)  # the later, taller one


def test_only_consecutive_valid_pulses_set_the_pulse_rate() -> None:
    # a narrow 3x spike after every other beat is detected and judged invalid; the intervals to
    # and from it (0.45 s, 0.55 s) are not used, so the rate is the beats' own 60 per minute
    fs = 100.0
    beats = [0.8 + k for k in range(38)]
    x = _bumps(40.0, fs, beats, [(b + 0.45, 3 * 12.0, 0.02) for b in beats[::2]])
    got = pi_window(x, (True,) * len(x), fs)
    assert isinstance(got, PiValue)
    assert got.pulse_rate_bpm == pytest.approx(60.0, abs=1.0)


def test_exactly_the_minimum_number_of_valid_pulses_is_computed_and_one_fewer_is_not() -> None:
    fs = 100.0  # ten pulses, each with a second of room on both sides, are all valid
    ten = _bumps(12.0, fs, [1.5 + k for k in range(10)])
    nine = _bumps(12.0, fs, [1.5 + k for k in range(9)])
    assert isinstance(pi_window(ten, (True,) * len(ten), fs), PiValue)
    assert pi_window(nine, (True,) * len(nine), fs) == NotComputed("too_few_valid_pulses")


def test_an_out_of_band_motion_tone_is_not_mistaken_for_breathing() -> None:
    # 15 breaths/min plus a stronger 60/min vibration: only the 6-30/min band is searched
    fs = 25.0
    t = np.arange(round(64 * fs)) / fs
    x = 0.05 * np.sin(2 * np.pi * (15.0 / 60.0) * t) + 0.3 * np.sin(2 * np.pi * 1.0 * t)
    got = rr_from_accel(tuple(float(v) for v in x), (True,) * len(t), fs)
    assert got == pytest.approx(15.0, abs=1.0)


def test_a_flat_topped_pulse_is_one_pulse_not_one_per_sample_above_the_floor() -> None:
    # a clipped pulse stays above the peak floor for longer than the refractory; only its
    # local maximum is a candidate
    fs = 100.0
    wide = np.asarray(_bumps(14.0, fs, [0.8 + k for k in range(12)], sigma_s=0.2))
    clipped = tuple(float(v) for v in np.minimum(wide, 1000.0 + 5.0))
    assert len(detect_pulses(clipped, (True,) * len(clipped), fs).times_s) == 12
