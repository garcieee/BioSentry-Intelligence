"""Tier B signal layer (M2b): PPG pulse detection and perfusion index (AC/DC).

Numpy only and detect-only, like ecg.py: each contiguous usable run is searched separately,
nothing is interpolated, and a window that cannot honestly give a perfusion index is
`NotComputed` with the reason (I1).

Perfusion index = pulsatile (AC) amplitude / local mean (DC) level x 100, per pulse, then the
window median. It is a trend against the patient's own baseline, not a quality index, and it is
only as meaningful as the raw channel: a front end that cancels DC or auto-scales its gain
changes it. That is a property of the device and is recorded in the model card, not corrected
here.

Known limit: a strong periodic artefact larger than the pulse (steady-cadence motion) can be
detected instead of the pulse. `pi_window` therefore reports the pulse rate and accepts the ECG
heart rate to cross-check against; without it, that case is not caught.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from biosentry.schemas import Provenance

from ...computed import NotComputed, Result
from ...signals import SignalInput, apply_windows
from .dsp import FloatArray, moving_average, true_runs

MIN_RUN_S = 5.0
REFRACTORY_S = 0.3
FOOT_SEARCH_S = 0.6  # the foot (minimum) is looked for this long before the systolic peak
SQI_MIN_CORR = 0.7  # per-pulse template correlation below this marks the pulse invalid
MIN_PULSES = 10  # valid pulses needed for a window's perfusion index
MIN_VALID_SHARE = 0.5  # valid pulses / detected pulses
PEAK_FRACTION = 0.35  # of the typical pulse amplitude
RATE_TOLERANCE = 0.2  # PPG pulse rate vs the ECG rate, as a fraction
_PRE_S = 0.4
_POST_S = 0.6


@dataclass(frozen=True, slots=True)
class Pulses:
    times_s: tuple[float, ...]  # systolic peak times, seconds from the start of the signal
    ac: tuple[float, ...]  # peak minus preceding foot of the smoothed raw signal
    dc: tuple[float, ...]  # local mean of the raw signal around the peak
    valid: tuple[bool, ...]  # pulse had a full foot window and matched the run's template
    run: tuple[int, ...]  # id of the contiguous usable run the pulse was found in


def _peaks(y: FloatArray, fs: float) -> list[int]:
    """Systolic peaks of the pulsatile component of one gap-free run."""
    block = max(1, round(REFRACTORY_S * fs))
    block_max = np.maximum.reduceat(y, np.arange(0, len(y), block))
    if block_max.size < 4:
        return []
    reference = float(np.median(np.sort(block_max)[-max(3, block_max.size // 4) :]))
    if reference <= 0.0:
        return []
    floor = PEAK_FRACTION * reference
    refractory = round(REFRACTORY_S * fs)
    inner = y[1:-1]
    candidates = np.flatnonzero((inner > y[:-2]) & (inner >= y[2:]) & (inner > floor)) + 1
    peaks: list[int] = []
    for index in candidates:
        i = int(index)
        if peaks and i - peaks[-1] < refractory:
            if y[i] > y[peaks[-1]]:
                peaks[-1] = i
            continue
        peaks.append(i)
    return peaks


def _pulses_in_run(
    x: FloatArray, fs: float
) -> tuple[list[int], list[float], list[float], list[bool]]:
    smooth = moving_average(x, round(0.08 * fs))
    y = smooth - moving_average(x, round(1.0 * fs))
    peaks = _peaks(y, fs)
    foot_span = round(FOOT_SEARCH_S * fs)
    dc_span = round(1.0 * fs)
    pre, post = round(_PRE_S * fs), round(_POST_S * fs)
    ac: list[float] = []
    dc: list[float] = []
    complete: list[bool] = []
    for p in peaks:
        has_window = p - max(foot_span, dc_span) >= 0 and p + dc_span < len(x)
        complete.append(has_window)
        if has_window:
            ac.append(float(smooth[p] - smooth[p - foot_span : p].min()))
            dc.append(float(x[p - dc_span : p + dc_span + 1].mean()))
        else:
            ac.append(float("nan"))
            dc.append(float("nan"))
    shaped = [k for k, p in enumerate(peaks) if p - pre >= 0 and p + post < len(y)]
    quality = [False] * len(peaks)
    if len(shaped) >= 3:
        stack = np.stack([y[peaks[k] - pre : peaks[k] + post + 1] for k in shaped])
        template = np.median(stack, axis=0)
        template = template - template.mean()
        norm = float(np.linalg.norm(template))
        if norm > 0.0:
            for k, row in zip(shaped, stack, strict=True):
                centred = row - row.mean()
                denom = float(np.linalg.norm(centred)) * norm
                quality[k] = denom > 0.0 and float(centred @ template) / denom >= SQI_MIN_CORR
    valid = [c and q for c, q in zip(complete, quality, strict=True)]
    return peaks, ac, dc, valid


def detect_pulses(samples: Sequence[float], usable: Sequence[bool], fs: float) -> Pulses:
    """Pulses in the usable parts of a raw PPG channel."""
    x = np.asarray(samples, dtype=np.float64)
    ok = np.asarray(usable, dtype=np.bool_) & np.isfinite(x)
    times: list[float] = []
    ac: list[float] = []
    dc: list[float] = []
    valid: list[bool] = []
    runs: list[int] = []
    for run_id, (lo, hi) in enumerate(true_runs(ok)):
        if hi - lo < round(MIN_RUN_S * fs):
            continue
        peaks, run_ac, run_dc, run_valid = _pulses_in_run(x[lo:hi], fs)
        for p, a, d, v in zip(peaks, run_ac, run_dc, run_valid, strict=True):
            times.append((lo + p) / fs)
            ac.append(a)
            dc.append(d)
            valid.append(v)
            runs.append(run_id)
    return Pulses(tuple(times), tuple(ac), tuple(dc), tuple(valid), tuple(runs))


@dataclass(frozen=True, slots=True)
class PiValue:
    pi_percent: float  # median over valid pulses of 100 x AC / DC
    n_pulses: int  # valid pulses behind it
    valid_share: float  # valid pulses / detected pulses
    pulse_rate_bpm: float  # median rate of consecutive valid pulses, for cross-checking vs ECG


def pi_window(
    samples: Sequence[float],
    usable: Sequence[bool],
    fs: float,
    *,
    expected_hr_bpm: float | None = None,
    rate_tolerance: float = RATE_TOLERANCE,
) -> PiValue | NotComputed:
    """Perfusion index for one raw PPG window, or the reason it was refused.

    With `expected_hr_bpm` (the ECG heart rate for the same window) a pulse rate that is not
    within `rate_tolerance` of it is refused: a strong periodic artefact, such as steady-cadence
    motion, can otherwise be mistaken for the pulse and produce a plausible but wrong number.
    """
    pulses = detect_pulses(samples, usable, fs)
    n = len(pulses.times_s)
    good = np.asarray(pulses.valid, dtype=np.bool_)
    if n == 0 or int(good.sum()) < MIN_PULSES:
        return NotComputed("too_few_valid_pulses")
    if good.mean() < MIN_VALID_SHARE:
        return NotComputed("low_signal_quality")
    ac = np.asarray(pulses.ac, dtype=np.float64)[good]
    dc = np.asarray(pulses.dc, dtype=np.float64)[good]
    if not np.all(dc > 0.0):
        return NotComputed("dc_not_positive")
    times = np.asarray(pulses.times_s, dtype=np.float64)
    run = np.asarray(pulses.run, dtype=np.int64)
    both = good[:-1] & good[1:] & (run[:-1] == run[1:])
    gaps = np.diff(times)[both]
    if gaps.size == 0:
        return NotComputed("too_few_valid_pulses")
    rate = float(np.median(60.0 / gaps))
    if (
        expected_hr_bpm is not None
        and abs(rate - expected_hr_bpm) > rate_tolerance * expected_hr_bpm
    ):
        return NotComputed("pulse_rate_disagrees_with_ecg")
    return PiValue(
        pi_percent=float(np.median(100.0 * ac / dc)),
        n_pulses=int(good.sum()),
        valid_share=float(good.mean()),
        pulse_rate_bpm=rate,
    )


def compute_pi(
    signal: SignalInput,
    provenance: Provenance,
    *,
    min_coverage: float = 0.5,
    expected_hr_bpm: float | None = None,
) -> tuple[Result[PiValue], ...]:
    """Perfusion index per complete window of a raw PPG SignalInput."""

    def one(samples: Sequence[float], usable: Sequence[bool]) -> PiValue | NotComputed:
        return pi_window(samples, usable, signal.fs, expected_hr_bpm=expected_hr_bpm)

    return apply_windows(signal, one, provenance=provenance, min_coverage=min_coverage)
