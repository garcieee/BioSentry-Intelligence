"""M4 leakage checks (skeleton). They run on the CP3b generator, so no credentialed data is
needed; the feature builders written later for eICU, MIMIC-IV and INSPIRE plug into the same
checks and must pass them before any model is trained.

A builder maps (per-minute series, t) to a flat dict of features for the prediction made at
minute t. The reference builder below is deliberately plain; it exists so the checks have
something real to run on and so a leaky or imputing variant can prove the checks bite.
"""

import math
from collections.abc import Callable, Iterable, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

Series = NDArray[np.float64]
Features = dict[str, float]
FeatureBuilder = Callable[[Mapping[str, Series], int], Features]

# Feature names must never carry another tier's verdict (Tier C fuses inputs, never outputs)
# or anything derived from the outcome.
FORBIDDEN_NAME_PARTS = (
    "news2", "tier_a", "tier_b", "tier_c", "finding", "kdigo", "arbiter", "escalat",
    "rank", "priority", "label", "outcome", "event",
)  # fmt: skip
WINDOWS_MIN = (60, 180)
MIN_POINTS_FOR_SLOPE = 10


def _slope_per_hour(y: Series) -> float:
    x = np.flatnonzero(~np.isnan(y)).astype(np.float64)
    if x.size < MIN_POINTS_FOR_SLOPE:
        return math.nan
    return float(np.polyfit(x, y[~np.isnan(y)], 1)[0] * 60.0)


def reference_features(minutes: Mapping[str, Series], t: int) -> Features:
    """Windowed features at minute t from minutes[: t + 1] only. Missing stays NaN."""
    out: Features = {}
    for vital, series in sorted(minutes.items()):
        past = series[: t + 1]
        valid = np.flatnonzero(~np.isnan(past))
        out[f"{vital}__missing"] = 0.0 if valid.size else 1.0
        out[f"{vital}__last"] = float(past[valid[-1]]) if valid.size else math.nan
        out[f"{vital}__age_min"] = float(t - valid[-1]) if valid.size else math.nan
        for w in WINDOWS_MIN:
            window = past[-w:]
            ok = window[~np.isnan(window)]
            out[f"{vital}__n_valid_{w}"] = float(ok.size)
            out[f"{vital}__median_{w}"] = float(np.median(ok)) if ok.size else math.nan
            out[f"{vital}__min_{w}"] = float(ok.min()) if ok.size else math.nan
            out[f"{vital}__max_{w}"] = float(ok.max()) if ok.size else math.nan
            out[f"{vital}__slope_per_h_{w}"] = _slope_per_hour(window)
    return out


def same_features(a: Features, b: Features) -> bool:
    if a.keys() != b.keys():
        return False
    return all((math.isnan(a[k]) and math.isnan(b[k])) or a[k] == b[k] for k in a)


def _differing(a: Features, b: Features) -> list[str]:
    return [
        k for k in sorted(a.keys() | b.keys())
        if not ((math.isnan(a.get(k, 0.0)) and math.isnan(b.get(k, 0.0))) or a.get(k) == b.get(k))
    ]  # fmt: skip


def with_future_replaced(minutes: Mapping[str, Series], t: int, how: str) -> dict[str, Series]:
    """Everything after minute t replaced: NaN, huge finite garbage, or reversed."""
    out: dict[str, Series] = {}
    for vital, series in minutes.items():
        s = series.copy()
        if how == "nan":
            s[t + 1 :] = np.nan
        elif how == "garbage":
            s[t + 1 :] = 1.0e6
        elif how == "reversed":
            s[t + 1 :] = s[t + 1 :][::-1]
        else:
            raise ValueError(how)
        out[vital] = s
    return out


def assert_no_future_dependence(
    builder: FeatureBuilder, minutes: Mapping[str, Series], t: int
) -> None:
    """Features at t must not change when anything after t changes."""
    base = builder(minutes, t)
    for how in ("nan", "garbage", "reversed"):
        changed = builder(with_future_replaced(minutes, t, how), t)
        diff = _differing(base, changed)
        assert not diff, f"features at t={t} depend on the future ({how}): {diff}"


def assert_missing_stays_missing(
    builder: FeatureBuilder, minutes: Mapping[str, Series], t: int
) -> None:
    """With a vital entirely missing, its value features are NaN (never 0) and flagged."""
    vital = next(iter(sorted(minutes)))
    blanked = {v: (np.full_like(s, np.nan) if v == vital else s) for v, s in minutes.items()}
    feats = builder(blanked, t)
    mine = {k: x for k, x in feats.items() if k.startswith(f"{vital}__")}
    assert mine, "the builder emits no features for the blanked vital"
    for name, value in mine.items():
        counts_or_flags = name.endswith("__missing") or "__n_valid_" in name
        if not counts_or_flags:
            assert math.isnan(value), f"{name}={value} for a vital with no data: that is a fill"
    assert feats[f"{vital}__missing"] == 1.0, "a missing vital must carry an explicit indicator"


def assert_no_verdict_features(names: Iterable[str]) -> None:
    bad = [n for n in names if any(part in n.lower() for part in FORBIDDEN_NAME_PARTS)]
    assert not bad, f"features named after another tier's verdict or the outcome: {bad}"


def assert_patient_level_split(train: Sequence[str], test: Sequence[str]) -> None:
    both = set(train) & set(test)
    assert not both, f"patients in both train and test: {sorted(both)}"
