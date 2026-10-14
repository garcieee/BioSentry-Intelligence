"""Small numpy helpers shared by the Tier B signal layer. Nothing here fills or pads a gap."""

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def moving_average(x: FloatArray, width: int) -> FloatArray:
    """Centred moving average that only ever uses samples that exist (no edge padding)."""
    width = min(max(1, width) | 1, len(x) if len(x) % 2 else len(x) - 1)
    if width <= 1:
        return x.copy()
    kernel = np.ones(width, dtype=np.float64)
    total = np.convolve(x, kernel, mode="same")
    count = np.convolve(np.ones_like(x), kernel, mode="same")
    return np.asarray(total / count, dtype=np.float64)


def true_runs(mask: NDArray[np.bool_]) -> list[tuple[int, int]]:
    """[start, stop) of every maximal run of True."""
    padded = np.concatenate(([False], mask, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    return [(int(a), int(b)) for a, b in zip(edges[0::2], edges[1::2], strict=True)]
