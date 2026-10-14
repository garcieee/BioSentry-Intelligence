"""Windowed signal input shared by Tier B/C adapters.

Models principle: every adapter takes `fs`, `window_s` and a validity mask, never imputes,
and says so with `NotComputed` for any window it cannot honestly score. Invalid samples are
passed to the function with the mask; they are never interpolated, filled or dropped here.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from biosentry.schemas import Provenance, QualityLevel

from .computed import Computed, NotComputed, Result, Window

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SignalInput:
    fs: float  # samples per second
    window_s: float  # window length in seconds
    samples: tuple[float, ...]
    valid: tuple[bool, ...]  # False = no usable sample here (gap, artefact, failed SQI)

    def __post_init__(self) -> None:
        if not (math.isfinite(self.fs) and self.fs > 0):
            raise ValueError("fs must be a positive, finite sampling rate")
        if not (math.isfinite(self.window_s) and self.window_s > 0):
            raise ValueError("window_s must be a positive, finite duration")
        if len(self.samples) != len(self.valid):
            raise ValueError("samples and valid must have the same length")
        if self.samples_per_window < 1:
            raise ValueError("a window must contain at least one sample")

    @property
    def samples_per_window(self) -> int:
        return round(self.fs * self.window_s)

    @property
    def usable(self) -> tuple[bool, ...]:
        """Valid by the mask and finite: a NaN sample is never usable."""
        return tuple(v and math.isfinite(x) for x, v in zip(self.samples, self.valid, strict=True))


def apply_windows(
    signal: SignalInput,
    fn: Callable[[Sequence[float], Sequence[bool]], T | NotComputed],
    *,
    provenance: Provenance,
    min_coverage: float = 0.5,
) -> tuple[Result[T], ...]:
    """Apply `fn` to each complete window; refuse windows with too little valid signal.

    `fn` receives the window's samples and its usable mask, and may itself refuse a window by
    returning `NotComputed`. A window with coverage below `min_coverage` is refused before
    `fn` runs; a partly valid window is `Computed` with quality `degraded`; only a fully
    valid window is `ok`. A trailing partial window is not emitted.
    """
    if not 0 < min_coverage <= 1:
        raise ValueError("min_coverage must be in (0, 1]")
    n = signal.samples_per_window
    usable = signal.usable
    results: list[Result[T]] = []
    for k in range(len(signal.samples) // n):
        lo, hi = k * n, (k + 1) * n
        coverage = sum(usable[lo:hi]) / n
        if coverage < min_coverage:
            results.append(NotComputed(f"coverage {coverage:.2f} below {min_coverage:.2f}"))
            continue
        value = fn(signal.samples[lo:hi], usable[lo:hi])
        if isinstance(value, NotComputed):
            results.append(value)
            continue
        quality = QualityLevel.ok if coverage == 1 else QualityLevel.degraded
        results.append(
            Computed(
                value=value,
                provenance=provenance.model_copy(update={"quality": quality}),
                window=Window(lo / signal.fs, hi / signal.fs, coverage),
            )
        )
    return tuple(results)
