"""The shared signal helpers, and a structural ratchet: the Tier B code never fills gaps."""

import ast
from pathlib import Path

import numpy as np

from biosentry.domain.scoring.tier_b import dsp

TIER_B = Path(__file__).resolve().parents[2] / "src" / "biosentry" / "domain" / "scoring" / "tier_b"
# Anything that invents samples: interpolation, resampling, fill-forward, spline fits.
FORBIDDEN_NAMES = {
    "interp",
    "interp1d",
    "interpolate",
    "griddata",
    "CubicSpline",
    "UnivariateSpline",
    "resample",
    "resample_poly",
    "decimate",
    "fillna",
    "ffill",
    "bfill",
    "nan_to_num_fill",
}
FORBIDDEN_MODULES = {"scipy", "pandas"}


def test_moving_average_uses_only_samples_that_exist_at_the_edges() -> None:
    got = dsp.moving_average(np.array([1.0, 2.0, 3.0, 4.0, 5.0]), 3)
    assert got.tolist() == [1.5, 2.0, 3.0, 4.0, 4.5]  # edges: mean of the 2 that exist, no padding


def test_moving_average_never_widens_beyond_the_signal() -> None:
    x = np.array([2.0, 4.0, 6.0])
    assert dsp.moving_average(x, 101).tolist() == [3.0, 4.0, 5.0]
    assert dsp.moving_average(x, 1).tolist() == [2.0, 4.0, 6.0]


def test_true_runs_finds_maximal_runs() -> None:
    mask = np.array([True, True, False, True, False, False, True, True, True])
    assert dsp.true_runs(mask) == [(0, 2), (3, 4), (6, 9)]
    assert dsp.true_runs(np.zeros(4, dtype=np.bool_)) == []


def test_tier_b_sources_contain_nothing_that_fills_or_resamples() -> None:
    sources = sorted(TIER_B.glob("*.py"))
    assert len(sources) >= 6  # ecg, hrv, burden, ppg, respiration, dsp (+ interface, __init__)
    offenders: list[str] = []
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: set[str] = set()
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.alias):
                names.add(node.name.split(".")[-1])
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".")[0] in FORBIDDEN_MODULES
            ):
                offenders.append(f"{path.name}: from {node.module}")
            if isinstance(node, ast.alias) and node.name.split(".")[0] in FORBIDDEN_MODULES:
                offenders.append(f"{path.name}: import {node.name}")
            for name in names & FORBIDDEN_NAMES:
                offenders.append(f"{path.name}: {name}")
    assert offenders == []
