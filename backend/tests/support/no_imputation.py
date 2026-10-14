"""`assert_no_imputation`: the check every Tier B/C adapter must pass.

Inject a gap into a clean signal and run the adapter twice. The adapter must (1) emit
nothing for any window that lies entirely inside the gap, (2) leave every window entirely
outside the gap exactly as it was, (3) never call a partly gapped window `ok` quality, and
(4) let the mask alone decide: what value a masked sample carries must not change the output.

(4) is the invariance check. NaN in a masked slot is the friendly case: an adapter that sums or
averages every sample "behaves" because NaN poisons or is filtered by `isfinite`. A masked slot
holding 1e9 or -1e9 is not friendly, and shows whether the adapter looked at a value the mask
says is not there (read it, clamped it, defaulted it to zero). It is run on the gap given and
on the same gap shifted by half a window, so a window that is only partly masked is always in
play whatever the caller's gap is aligned to.
"""

from collections.abc import Callable, Sequence
from typing import Any

from biosentry.domain.computed import Computed, NotComputed
from biosentry.domain.signals import SignalInput
from biosentry.schemas import QualityLevel

# Finite values a masked sample must never be able to influence the output with.
GARBAGE = (1e9, -1e9)


def with_gap(signal: SignalInput, start: int, stop: int, fill: float = float("nan")) -> SignalInput:
    """The same signal with samples [start, stop) masked: `fill` as the value, valid False."""
    samples = tuple(fill if start <= i < stop else x for i, x in enumerate(signal.samples))
    valid = tuple(False if start <= i < stop else v for i, v in enumerate(signal.valid))
    return SignalInput(signal.fs, signal.window_s, samples, valid)


def _same(a: object, b: object) -> bool:
    return a == b or repr(a) == repr(b)  # NaN is not equal to itself, but its repr is


def assert_mask_invariance(
    process: Callable[[SignalInput], Sequence[Computed[Any] | NotComputed]],
    signal: SignalInput,
    gap: tuple[int, int],
) -> None:
    """The output must not depend on the value a masked sample carries, only on the mask."""
    start, stop = gap
    half = max(1, signal.samples_per_window // 2)
    masks = [(start, stop)]
    shifted = (start + half, min(stop + half, len(signal.samples)))
    if shifted[0] < shifted[1] and shifted != (start, stop):
        masks.append(shifted)  # cuts the first and last masked windows in half
    for lo, hi in masks:
        reference = process(with_gap(signal, lo, hi))
        for fill in GARBAGE:
            other = process(with_gap(signal, lo, hi, fill=fill))
            assert len(other) == len(reference), "masked values must not change the window count"
            for k, (before, after) in enumerate(zip(reference, other, strict=True)):
                assert _same(before, after), (
                    f"window {k} changed when the masked samples [{lo}, {hi}) held {fill:g} "
                    "instead of NaN: the adapter reads values the mask says are not there"
                )


def assert_no_imputation(
    process: Callable[[SignalInput], Sequence[Computed[Any] | NotComputed]],
    signal: SignalInput,
    gap: tuple[int, int],
) -> None:
    assert_mask_invariance(process, signal, gap)
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
