"""Tier B signal layer (M2a): HRV (RMSSD, SDNN) on valid normal-to-normal intervals only.

An interval is used only when both beats passed the quality check, both lie in the same gap-free
run, the interval is physiologically plausible, and it is not ectopic. Excluded intervals are
counted and reported, never replaced; a window that cannot honestly yield HRV is `NotComputed`
with the reason (I1).

Thresholds are design parameters taken from the literature, not validated on patch data:
- Munoz et al. 2015 (PLoS One 10(9):e0138921): a single 10 s recording gives a valid RMSSD,
  SDNN needs 30 s.
- Cajal et al. 2022 (Sensors 22(15):5774, on 2-minute segments from simulated and smartwatch
  data): discard segments with more than 35% missing beats or bursts longer than 20 s; its
  limit for RMSSD alone is 25% of scattered missing beats, which is applied to both metrics.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from biosentry.schemas import Provenance

from ...computed import NotComputed, Result
from ...signals import SignalInput, apply_windows
from .ecg import Beats, detect_beats

MIN_IBI_S = 0.3
MAX_IBI_S = 2.0
ECTOPIC_FRACTION = 0.20  # an interval this far from its neighbours' median is ectopic
NEIGHBOURS = 5  # intervals on each side that form the local median
MIN_NN_S_RMSSD = 10.0
MIN_NN_S_SDNN = 30.0
MIN_NN_COVERAGE = 0.75  # valid NN seconds / window seconds (25% missing at most)
MAX_GAP_S = 20.0
MAX_ECTOPIC_SHARE = 0.30  # of plausible intervals: above this the rhythm is "irregular"


@dataclass(frozen=True, slots=True)
class HrvValue:
    rmssd_ms: float
    sdnn_ms: float
    mean_hr_bpm: float
    n_nn: int  # valid normal-to-normal intervals used
    n_excluded: int  # consecutive-beat pairs dropped (gap, bad beat, implausible, ectopic)
    nn_coverage: float  # seconds covered by valid NN / window seconds


def nn_intervals(beats: Beats) -> tuple[NDArray[np.float64], int, int]:
    """Per consecutive-beat pair: the NN interval in seconds, or NaN where it is excluded.

    Also returns the number of plausible intervals dropped as ectopic and the number of
    plausible intervals considered, so the caller can tell "noisy" from "irregular".
    """
    t = np.asarray(beats.times_s, dtype=np.float64)
    if len(t) < 2:
        return np.empty(0, dtype=np.float64), 0, 0
    good = np.asarray(beats.valid, dtype=np.bool_)
    run = np.asarray(beats.run, dtype=np.int64)
    ibi = np.diff(t)
    plausible = (
        good[:-1] & good[1:] & (run[:-1] == run[1:]) & (ibi >= MIN_IBI_S) & (ibi <= MAX_IBI_S)
    )
    nn = np.where(plausible, ibi, np.nan)
    out = nn.copy()
    ectopic = 0
    for index in np.flatnonzero(plausible):
        i = int(index)
        lo, hi = max(0, i - NEIGHBOURS), min(len(nn), i + NEIGHBOURS + 1)
        around = np.delete(nn[lo:hi], i - lo)
        around = around[np.isfinite(around)]
        if len(around) >= 3:
            med = float(np.median(around))
            if abs(nn[i] - med) > ECTOPIC_FRACTION * med:
                out[i] = np.nan
                ectopic += 1
    return out, ectopic, int(np.count_nonzero(plausible))


def _longest_gap_s(usable: Sequence[bool], samples: Sequence[float], fs: float) -> float:
    bad = ~(np.asarray(usable, dtype=np.bool_) & np.isfinite(np.asarray(samples, dtype=np.float64)))
    longest = run = 0
    for flag in bad:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return longest / fs


def hrv_window(
    samples: Sequence[float], usable: Sequence[bool], fs: float
) -> HrvValue | NotComputed:
    """RMSSD, SDNN and mean HR for one ECG window, or the reason it was refused."""
    window_s = len(samples) / fs
    if _longest_gap_s(usable, samples, fs) > MAX_GAP_S:
        return NotComputed("gap_longer_than_20s")
    nn, ectopic, plausible = nn_intervals(detect_beats(samples, usable, fs))
    if plausible and ectopic / plausible > MAX_ECTOPIC_SHARE:
        return NotComputed("irregular_rhythm")
    valid = np.isfinite(nn)
    covered_s = float(nn[valid].sum()) if nn.size else 0.0
    if covered_s < MIN_NN_S_SDNN:
        return NotComputed("insufficient_valid_nn")
    if covered_s / window_s < MIN_NN_COVERAGE:
        return NotComputed("nn_coverage_below_75pct")
    pairs = valid[:-1] & valid[1:]
    if float(nn[:-1][pairs].sum()) < MIN_NN_S_RMSSD:
        return NotComputed("insufficient_consecutive_nn")
    diffs = np.diff(nn)[pairs]
    good_nn = nn[valid]
    return HrvValue(
        rmssd_ms=float(np.sqrt(np.mean(diffs * diffs)) * 1000.0),
        sdnn_ms=float(np.std(good_nn, ddof=1) * 1000.0),
        mean_hr_bpm=float(60.0 / np.mean(good_nn)),
        n_nn=int(valid.sum()),
        n_excluded=int(nn.size - valid.sum()),
        nn_coverage=covered_s / window_s,
    )


def compute_hrv(
    signal: SignalInput,
    provenance: Provenance,
    *,
    min_coverage: float = MIN_NN_COVERAGE,
) -> tuple[Result[HrvValue], ...]:
    """HRV per complete window of an ECG SignalInput; refused windows say why."""

    def one(samples: Sequence[float], usable: Sequence[bool]) -> HrvValue | NotComputed:
        return hrv_window(samples, usable, signal.fs)

    return apply_windows(signal, one, provenance=provenance, min_coverage=min_coverage)
