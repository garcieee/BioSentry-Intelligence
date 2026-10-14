"""Windowed signal machinery and the assert_no_imputation helper."""

import math
from collections.abc import Sequence

import pytest
from no_imputation import assert_no_imputation, with_gap

from biosentry.domain.computed import Computed, NotComputed, Result
from biosentry.domain.signals import SignalInput, apply_windows
from biosentry.schemas import Provenance, QualityLevel
from samples import provenance

PROV = Provenance.model_validate(provenance())


def make(n_windows: int = 10, per_window: int = 4) -> SignalInput:
    samples = tuple(float(i % 7) for i in range(n_windows * per_window))
    return SignalInput(fs=4.0, window_s=1.0, samples=samples, valid=(True,) * len(samples))


def mean(samples: Sequence[float], usable: Sequence[bool]) -> float:
    values = [x for x, ok in zip(samples, usable, strict=True) if ok]
    return sum(values) / len(values)


def mean_windows(signal: SignalInput) -> tuple[Result[float], ...]:
    return apply_windows(signal, mean, provenance=PROV)


@pytest.mark.parametrize(
    ("fs", "window_s"), [(0, 1), (-1, 1), (math.nan, 1), (4, 0), (4, math.inf), (1, 0.1)]
)
def test_invalid_rate_or_window_is_rejected(fs: float, window_s: float) -> None:
    with pytest.raises(ValueError, match=r"positive|at least one"):
        SignalInput(fs, window_s, (1.0,), (True,))


def test_samples_and_mask_must_align() -> None:
    with pytest.raises(ValueError, match="same length"):
        SignalInput(4.0, 1.0, (1.0, 2.0), (True,))


def test_clean_signal_gives_ok_windows_with_full_coverage() -> None:
    results = mean_windows(make())
    assert len(results) == 10
    assert all(isinstance(r, Computed) and r.quality is QualityLevel.ok for r in results)
    assert all(isinstance(r, Computed) and r.window.coverage == 1.0 for r in results)


def test_window_times_are_in_seconds_from_the_start() -> None:
    first, second = mean_windows(make())[:2]
    assert isinstance(first, Computed)
    assert isinstance(second, Computed)
    assert (first.window.start_s, first.window.end_s) == (0.0, 1.0)
    assert (second.window.start_s, second.window.end_s) == (1.0, 2.0)


def test_a_trailing_partial_window_is_not_emitted() -> None:
    signal = SignalInput(4.0, 1.0, (1.0,) * 6, (True,) * 6)
    assert len(mean_windows(signal)) == 1


def test_fully_invalid_window_is_refused_not_filled() -> None:
    results = mean_windows(with_gap(make(), 8, 12))
    assert isinstance(results[2], NotComputed)
    assert "coverage 0.00" in results[2].reason


def test_partly_valid_window_is_degraded_and_reports_its_coverage() -> None:
    results = mean_windows(with_gap(make(), 8, 10))  # half of window 2
    r = results[2]
    assert isinstance(r, Computed)
    assert r.quality is QualityLevel.degraded
    assert r.window.coverage == 0.5


def test_window_below_min_coverage_is_refused() -> None:
    results = apply_windows(
        with_gap(make(), 8, 11), mean, provenance=PROV, min_coverage=0.5
    )  # 1 of 4 usable
    assert isinstance(results[2], NotComputed)


def test_nan_sample_is_never_usable_even_if_the_mask_says_valid() -> None:
    signal = SignalInput(4.0, 1.0, (1.0, math.nan, 3.0, 4.0), (True,) * 4)
    assert signal.usable == (True, False, True, True)
    (r,) = mean_windows(signal)
    assert isinstance(r, Computed)
    assert r.value == pytest.approx(8 / 3)
    assert r.quality is QualityLevel.degraded


def test_function_may_refuse_a_window_itself() -> None:
    def refuse(samples: Sequence[float], usable: Sequence[bool]) -> float | NotComputed:
        return NotComputed("sqi_failed")

    results = apply_windows(make(), refuse, provenance=PROV)
    assert results == (NotComputed("sqi_failed"),) * 10


def test_min_coverage_must_be_a_fraction() -> None:
    for bad in (0, -0.1, 1.5):
        with pytest.raises(ValueError, match="min_coverage"):
            apply_windows(make(), mean, provenance=PROV, min_coverage=bad)


def test_the_original_provenance_is_not_mutated() -> None:
    mean_windows(with_gap(make(), 8, 10))
    assert PROV.quality is QualityLevel.ok


# --- assert_no_imputation -----------------------------------------------------------------


def test_a_gap_respecting_adapter_passes_the_check() -> None:
    assert_no_imputation(mean_windows, make(), gap=(8, 24))


def test_an_adapter_that_interpolates_across_the_gap_is_caught() -> None:
    def imputing(signal: SignalInput) -> tuple[Result[float], ...]:
        # Fills every invalid sample with the previous valid one, then scores every window.
        filled: list[float] = []
        last = 0.0
        for x, ok in zip(signal.samples, signal.usable, strict=True):
            last = x if ok else last
            filled.append(last)
        patched = SignalInput(signal.fs, signal.window_s, tuple(filled), (True,) * len(filled))
        return apply_windows(patched, mean, provenance=PROV)

    with pytest.raises(AssertionError, match="inside the gap"):
        assert_no_imputation(imputing, make(), gap=(8, 24))


def test_an_adapter_that_changes_windows_outside_the_gap_is_caught() -> None:
    def leaky(signal: SignalInput) -> tuple[Result[float], ...]:
        results = list(mean_windows(signal))
        if not all(signal.valid):  # a gap anywhere perturbs every window
            results = [
                Computed(r.value + 1, r.provenance, r.window) if isinstance(r, Computed) else r
                for r in results
            ]
        return tuple(results)

    with pytest.raises(AssertionError, match="outside the gap but changed"):
        assert_no_imputation(leaky, make(), gap=(8, 24))


def test_a_vacuous_check_is_refused() -> None:
    with pytest.raises(AssertionError, match="no whole window"):
        assert_no_imputation(mean_windows, make(), gap=(9, 11))
