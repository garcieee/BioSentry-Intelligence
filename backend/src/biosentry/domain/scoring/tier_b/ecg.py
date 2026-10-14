"""Tier B signal layer (M2a): R-peak detection with a per-beat quality check.

Detect-only and numpy-only. The detector works on each contiguous usable run separately and
never bridges a gap: a beat is only ever reported where signal was actually there (I1).
A beat that cannot be judged (too close to a run edge, or no template yet) is marked invalid,
not guessed. NeuroKit2's cleaning and peak-correction paths interpolate by default and are
deliberately not used.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .dsp import moving_average, true_runs

FloatArray = NDArray[np.float64]

MIN_RUN_S = 3.0  # a usable run shorter than this is not searched for beats
REFRACTORY_S = 0.25  # two beats closer than this are one beat
SQI_MIN_CORR = 0.6  # per-beat template correlation below this marks the beat invalid
QRS_THRESHOLD_FRACTION = 0.2  # of the typical QRS slope-energy peak
_PRE_S = 0.2  # beat window around the R peak used for the template check
_POST_S = 0.4


@dataclass(frozen=True, slots=True)
class Beats:
    times_s: tuple[float, ...]  # R-peak times, seconds from the start of the signal
    valid: tuple[bool, ...]  # beat passed the template-correlation check
    run: tuple[int, ...]  # id of the contiguous usable run the beat was found in
    amplitude: tuple[float, ...]  # |detrended signal| at the R peak, in signal units


def _qrs_threshold(energy: FloatArray, fs: float) -> float:
    """A fraction of the typical QRS slope-energy peak.

    The energy trace is cut into refractory-length blocks and each block keeps its maximum, so
    thousands of tiny noise wiggles count once per block. The typical QRS peak is the median of
    the strongest tenth of those block maxima; P and T waves carry a few percent of a QRS's
    slope energy and stay below the fraction.
    """
    block = max(1, round(REFRACTORY_S * fs))
    peaks = np.maximum.reduceat(energy, np.arange(0, len(energy), block))
    if peaks.size < 4:
        return 0.0
    strongest = np.sort(peaks)[-max(3, peaks.size // 10) :]
    return QRS_THRESHOLD_FRACTION * float(np.median(strongest))


def _detect_run(x: FloatArray, fs: float) -> tuple[list[int], FloatArray]:
    """R-peak sample indices in one gap-free run, plus the detrended signal."""
    detrended = x - moving_average(x, round(0.75 * fs))
    smooth = moving_average(detrended, round(0.02 * fs))
    slope = np.diff(smooth, prepend=smooth[0])
    energy = moving_average(slope * slope, round(0.12 * fs))
    threshold = _qrs_threshold(energy, fs)
    if threshold <= 0.0:
        return [], detrended
    reach = round(0.05 * fs)
    refractory = round(REFRACTORY_S * fs)
    peaks: list[int] = []
    for start, stop in true_runs(energy > threshold):
        lo, hi = max(0, start - reach), min(len(smooth), stop + reach)
        i = lo + int(np.argmax(np.abs(smooth[lo:hi])))
        if peaks and i - peaks[-1] < refractory:
            if abs(smooth[i]) > abs(smooth[peaks[-1]]):
                peaks[-1] = i
            continue
        peaks.append(i)
    return peaks, detrended


def _beat_quality(y: FloatArray, peaks: list[int], fs: float) -> list[bool]:
    """Pearson correlation of each beat with the run's median beat >= SQI_MIN_CORR."""
    pre, post = round(_PRE_S * fs), round(_POST_S * fs)
    full = [k for k, p in enumerate(peaks) if p - pre >= 0 and p + post < len(y)]
    quality = [False] * len(peaks)
    if len(full) < 3:
        return quality
    stack = np.stack([y[peaks[k] - pre : peaks[k] + post + 1] for k in full])
    template = np.median(stack, axis=0)
    template = template - template.mean()
    t_norm = float(np.linalg.norm(template))
    if t_norm == 0.0:
        return quality
    for k, row in zip(full, stack, strict=True):
        centred = row - row.mean()
        denom = float(np.linalg.norm(centred)) * t_norm
        quality[k] = denom > 0.0 and float(centred @ template) / denom >= SQI_MIN_CORR
    return quality


def detect_beats(samples: Sequence[float], usable: Sequence[bool], fs: float) -> Beats:
    """R peaks in the usable parts of a single-lead ECG, in seconds from the signal start."""
    x = np.asarray(samples, dtype=np.float64)
    ok = np.asarray(usable, dtype=np.bool_) & np.isfinite(x)
    times: list[float] = []
    valid: list[bool] = []
    runs: list[int] = []
    amplitudes: list[float] = []
    for run_id, (lo, hi) in enumerate(true_runs(ok)):
        if hi - lo < round(MIN_RUN_S * fs):
            continue
        peaks, detrended = _detect_run(x[lo:hi], fs)
        for p, q in zip(peaks, _beat_quality(detrended, peaks, fs), strict=True):
            times.append((lo + p) / fs)
            valid.append(q)
            runs.append(run_id)
            amplitudes.append(float(abs(detrended[p])))
    return Beats(tuple(times), tuple(valid), tuple(runs), tuple(amplitudes))
