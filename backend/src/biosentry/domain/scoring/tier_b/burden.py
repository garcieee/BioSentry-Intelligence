"""Tier B signal layer (M2a): coverage-aware tachycardia burden and a robust personal baseline.

Burden is minutes at or above a threshold divided by VALID minutes, always reported with the
coverage it rests on. A gap is neither normal nor abnormal: it leaves the denominator, and a
series with too little coverage is refused rather than extrapolated (I1).

The baseline is a pure function of the stored per-minute rows of the current admission
(median and MAD of the most recent valid minutes). It is never stored as a profile and never
carried across admissions.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ...computed import NotComputed

HR_BURDEN_BPM = 110.0
MIN_BURDEN_COVERAGE = 0.5
BASELINE_HORIZON_MIN = 360  # the last 6 h of rows
BASELINE_MIN_VALID = 60  # at least an hour of valid minutes
MAD_TO_SD = 1.4826  # MAD -> standard deviation for a normal distribution


@dataclass(frozen=True, slots=True)
class BurdenValue:
    burden: float  # minutes at/above threshold / valid minutes, 0..1
    minutes_over: int
    valid_minutes: int
    coverage: float  # valid minutes / minutes in the series, 0..1


def hr_burden(
    hr_bpm: Sequence[float],
    usable: Sequence[bool],
    *,
    threshold_bpm: float = HR_BURDEN_BPM,
    min_coverage: float = MIN_BURDEN_COVERAGE,
) -> BurdenValue | NotComputed:
    """Share of valid minutes with HR >= threshold; refused below `min_coverage`."""
    if len(hr_bpm) != len(usable):
        raise ValueError("hr_bpm and usable must have the same length")
    if not hr_bpm:
        return NotComputed("no_minutes")
    x = np.asarray(hr_bpm, dtype=np.float64)
    ok = np.asarray(usable, dtype=np.bool_) & np.isfinite(x)
    valid = int(ok.sum())
    coverage = valid / len(hr_bpm)
    if valid == 0 or coverage < min_coverage:
        return NotComputed("coverage_below_minimum")
    over = int(np.count_nonzero(x[ok] >= threshold_bpm))
    return BurdenValue(
        burden=over / valid, minutes_over=over, valid_minutes=valid, coverage=coverage
    )


@dataclass(frozen=True, slots=True)
class Baseline:
    median: float
    mad: float  # median absolute deviation, unscaled
    n: int  # valid minutes behind it

    @property
    def scale(self) -> float:
        """Robust standard-deviation equivalent."""
        return self.mad * MAD_TO_SD


def robust_baseline(
    values: Sequence[float],
    usable: Sequence[bool],
    *,
    horizon: int = BASELINE_HORIZON_MIN,
    min_valid: int = BASELINE_MIN_VALID,
) -> Baseline | NotComputed:
    """Median/MAD of the valid rows among the last `horizon`; refused with too few."""
    if len(values) != len(usable):
        raise ValueError("values and usable must have the same length")
    x = np.asarray(values[-horizon:], dtype=np.float64)
    ok = np.asarray(usable[-horizon:], dtype=np.bool_) & np.isfinite(x)
    if int(ok.sum()) < min_valid:
        return NotComputed("baseline_not_established")
    v = x[ok]
    med = float(np.median(v))
    return Baseline(median=med, mad=float(np.median(np.abs(v - med))), n=int(v.size))


def robust_z(value: float, baseline: Baseline, *, min_scale: float = 1e-9) -> float | NotComputed:
    """How many robust standard deviations `value` sits from the baseline."""
    if not math.isfinite(value):
        return NotComputed("value_not_finite")
    if baseline.scale < min_scale:
        return NotComputed("baseline_has_no_spread")
    return (value - baseline.median) / baseline.scale
