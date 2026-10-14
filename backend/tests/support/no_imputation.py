"""`assert_no_imputation`: the check every Tier B/C adapter must pass.

Inject a gap into a clean signal and run the adapter twice. The adapter must (1) emit
nothing for any window that lies entirely inside the gap, (2) leave every window entirely
outside the gap exactly as it was, and (3) never call a partly gapped window `ok` quality.
"""

from collections.abc import Callable, Sequence
from typing import Any

from biosentry.domain.computed import Computed, NotComputed
from biosentry.domain.signals import SignalInput
from biosentry.schemas import QualityLevel


def with_gap(signal: SignalInput, start: int, stop: int) -> SignalInput:
    """The same signal with samples [start, stop) removed: NaN value and valid False."""
    samples = tuple(float("nan") if start <= i < stop else x for i, x in enumerate(signal.samples))
    valid = tuple(False if start <= i < stop else v for i, v in enumerate(signal.valid))
    return SignalInput(signal.fs, signal.window_s, samples, valid)


def assert_no_imputation(
    process: Callable[[SignalInput], Sequence[Computed[Any] | NotComputed]],
    signal: SignalInput,
    gap: tuple[int, int],
) -> None:
    start, stop = gap
    n = signal.samples_per_window
    clean = process(signal)
    gapped = process(with_gap(signal, start, stop))
    assert len(gapped) == len(clean), "a gap must not change the number of windows"

    inside = [k for k in range(len(clean)) if start <= k * n and (k + 1) * n <= stop]
    assert inside, "the gap covers no whole window, so this check would prove nothing"
    assert any(isinstance(clean[k], Computed) for k in inside), (
        "the clean signal produces no output inside the gap window, so the check is vacuous"
    )

    for k, (before, after) in enumerate(zip(clean, gapped, strict=True)):
        lo, hi = k * n, (k + 1) * n
        if k in inside:
            assert isinstance(after, NotComputed), (
                f"window {k} lies inside the gap but emitted {after!r}: that is imputation"
            )
        elif hi <= start or lo >= stop:
            assert after == before, f"window {k} is outside the gap but changed"
        elif isinstance(after, Computed):
            assert after.quality is not QualityLevel.ok, f"window {k} is gapped but claims ok"
            assert after.window.coverage < 1.0, f"window {k} is gapped but reports full coverage"
