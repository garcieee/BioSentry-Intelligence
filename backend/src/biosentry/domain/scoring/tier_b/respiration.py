"""Tier B signal layer (M2b): agreement-gated respiratory rate.

Three independent estimators each propose a rate for a window: the amplitude of the ECG R peaks,
the amplitude of the PPG pulses, and the chest accelerometer. A rate is reported only when at
least two of them agree within a tolerance and there is only one such group; otherwise the
window is `NotComputed` with the reason (two different agreeing pairs are ambiguous: choosing
one would be a guess). The beat-based estimators work on irregularly spaced samples with a
Lomb-Scargle periodogram, so no resampling or interpolation ever happens (I1).

Freedom to operate: respiratory-rate-from-ECG/PPG methods are covered by an Oxford patent
(US11103155B2); this implementation has not been cleared against it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from biosentry.schemas import Provenance, QualityLevel

from ...computed import Computed, NotComputed, Result, Window
from ...signals import SignalInput
from .dsp import FloatArray, true_runs
from .ecg import detect_beats
from .ppg import detect_pulses

BAND_BPM = (6.0, 30.0)  # plausible adult breathing rates
AGREEMENT_BPM = 3.0  # estimators within this of each other agree
MIN_PROMINENCE = 8.0  # spectral peak power / mean band power (noise alone: median 3.8, max 7.1)
MIN_BEATS = 8  # beat-based estimators need at least this many valid beats
MIN_ACCEL_RUN_S = 20.0
_N_FREQ = 241


@dataclass(frozen=True, slots=True)
class RrValue:
    breaths_per_min: float  # mean of the agreeing estimators
    estimators: tuple[str, ...]  # the ones that agreed
    spread_bpm: float  # largest difference among the agreeing estimators
    n_available: int  # estimators that produced a rate at all


def lomb_scargle_peak(t: FloatArray, y: FloatArray) -> tuple[float, float] | None:
    """Dominant rate (breaths/min) and its prominence in BAND_BPM for irregular samples.

    Prominence is peak power over mean power across the band; a pure tone scores far above
    MIN_PROMINENCE and noise rarely does. Returns None if there is nothing to estimate.
    """
    if t.size < MIN_BEATS or float(np.ptp(y)) == 0.0:
        return None
    y = y - y.mean()
    freqs = np.linspace(BAND_BPM[0], BAND_BPM[1], _N_FREQ) / 60.0
    omega = 2.0 * np.pi * freqs[:, None]  # (F, 1)
    wt = omega * t[None, :]  # (F, N)
    tau = np.arctan2(np.sin(2.0 * wt).sum(axis=1), np.cos(2.0 * wt).sum(axis=1)) / (
        2.0 * omega[:, 0]
    )
    arg = omega * (t[None, :] - tau[:, None])
    c, s = np.cos(arg), np.sin(arg)
    with np.errstate(divide="ignore", invalid="ignore"):
        power = 0.5 * (((c @ y) ** 2) / (c * c).sum(axis=1) + ((s @ y) ** 2) / (s * s).sum(axis=1))
    power = np.nan_to_num(power, nan=0.0, posinf=0.0, neginf=0.0)
    mean_power = float(power.mean())
    if mean_power <= 0.0:
        return None
    k = int(np.argmax(power))
    return float(freqs[k] * 60.0), float(power[k]) / mean_power


def _from_beats(times: FloatArray, values: FloatArray) -> float | None:
    peak = lomb_scargle_peak(times, values)
    if peak is None or peak[1] < MIN_PROMINENCE:
        return None
    return peak[0]


def rr_from_ecg(samples: Sequence[float], usable: Sequence[bool], fs: float) -> float | None:
    """Breaths/min from the amplitude modulation of valid R peaks."""
    beats = detect_beats(samples, usable, fs)
    keep = np.asarray(beats.valid, dtype=np.bool_)
    if int(keep.sum()) < MIN_BEATS:
        return None
    return _from_beats(
        np.asarray(beats.times_s, dtype=np.float64)[keep],
        np.asarray(beats.amplitude, dtype=np.float64)[keep],
    )


def rr_from_ppg(samples: Sequence[float], usable: Sequence[bool], fs: float) -> float | None:
    """Breaths/min from the amplitude modulation of valid PPG pulses."""
    pulses = detect_pulses(samples, usable, fs)
    keep = np.asarray(pulses.valid, dtype=np.bool_)
    if int(keep.sum()) < MIN_BEATS:
        return None
    return _from_beats(
        np.asarray(pulses.times_s, dtype=np.float64)[keep],
        np.asarray(pulses.ac, dtype=np.float64)[keep],
    )


def rr_from_accel(samples: Sequence[float], usable: Sequence[bool], fs: float) -> float | None:
    """Breaths/min from chest motion: spectral peak of the longest gap-free run."""
    x = np.asarray(samples, dtype=np.float64)
    ok = np.asarray(usable, dtype=np.bool_) & np.isfinite(x)
    runs = [r for r in true_runs(ok) if (r[1] - r[0]) / fs >= MIN_ACCEL_RUN_S]
    if not runs:
        return None
    lo, hi = max(runs, key=lambda r: r[1] - r[0])
    seg = x[lo:hi] - x[lo:hi].mean()
    if float(np.ptp(seg)) == 0.0:
        return None
    n_fft = 8 * len(seg)
    spectrum = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n=n_fft)) ** 2
    freqs_bpm = np.fft.rfftfreq(n_fft, d=1.0 / fs) * 60.0
    band = (freqs_bpm >= BAND_BPM[0]) & (freqs_bpm <= BAND_BPM[1])
    if not band.any():
        return None
    in_band = spectrum[band]
    mean_power = float(in_band.mean())
    if mean_power <= 0.0 or float(in_band.max()) / mean_power < MIN_PROMINENCE:
        return None
    return float(freqs_bpm[band][int(np.argmax(in_band))])


def agree(
    estimates: Mapping[str, float], tolerance: float = AGREEMENT_BPM
) -> RrValue | NotComputed:
    """The one largest group of estimators that all lie within `tolerance` of one another.

    Two different largest groups (10, 12 and 14.9 breaths/min with a tolerance of 3: 10 and 12
    agree, 12 and 14.9 agree, 10 and 14.9 do not) are ambiguous and refused: any choice between
    them would be a guess, and we never guess (I1).
    """
    if len(estimates) < 2:
        return NotComputed("insufficient_estimators")
    names = sorted(estimates, key=lambda n: estimates[n])
    groups = [
        tuple(n for n in names[i:] if estimates[n] - estimates[first] <= tolerance)
        for i, first in enumerate(names)
    ]
    size = max(len(group) for group in groups)
    if size < 2:
        return NotComputed("estimators_disagree")
    largest = [group for group in groups if len(group) == size]
    if len(largest) > 1:
        return NotComputed("estimators_ambiguous")
    rates = [estimates[n] for n in largest[0]]
    return RrValue(
        breaths_per_min=float(np.mean(rates)),
        estimators=tuple(sorted(largest[0])),
        spread_bpm=float(max(rates) - min(rates)),
        n_available=len(estimates),
    )


def rr_windows(
    ecg: SignalInput,
    ppg: SignalInput | None,
    accel: SignalInput | None,
    provenance: Provenance,
    *,
    min_coverage: float = 0.5,
) -> tuple[Result[RrValue], ...]:
    """Agreement-gated respiratory rate per complete window.

    All channels share `window_s` and a start time. A channel whose window has less than
    `min_coverage` valid signal simply does not vote; fewer than two voters, no two that
    agree, or two different pairs that agree (ambiguous), refuses the window. The window's
    coverage is that of the least-covered voter.
    """
    channels: list[tuple[str, SignalInput]] = [("ecg", ecg)]
    if ppg is not None:
        channels.append(("ppg", ppg))
    if accel is not None:
        channels.append(("accel", accel))
    for _, channel in channels:
        if channel.window_s != ecg.window_s:
            raise ValueError("all channels must share window_s")
    estimators = {"ecg": rr_from_ecg, "ppg": rr_from_ppg, "accel": rr_from_accel}
    count = min(len(c.samples) // c.samples_per_window for _, c in channels)
    results: list[Result[RrValue]] = []
    for k in range(count):
        votes: dict[str, float] = {}
        coverage = 1.0
        for name, channel in channels:
            n = channel.samples_per_window
            lo, hi = k * n, (k + 1) * n
            usable = channel.usable[lo:hi]
            share = sum(usable) / n
            if share < min_coverage:
                continue
            rate = estimators[name](channel.samples[lo:hi], usable, channel.fs)
            if rate is not None:
                votes[name] = rate
                coverage = min(coverage, share)
        verdict = agree(votes)
        if isinstance(verdict, NotComputed):
            results.append(verdict)
            continue
        quality = QualityLevel.ok if coverage == 1.0 else QualityLevel.degraded
        results.append(
            Computed(
                value=verdict,
                provenance=provenance.model_copy(update={"quality": quality}),
                window=Window(k * ecg.window_s, (k + 1) * ecg.window_s, coverage),
            )
        )
    return tuple(results)
