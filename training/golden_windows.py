"""Seeded synthetic 10 s ECG windows for the rhythm head's parity vectors (numpy only).

These are generated, never PhysioNet records (P6): sums of Gaussian waves on noise, chosen to
drive the network's activations negative and large. `backend/tests/unit/test_rhythm_artifacts.py`
regenerates them from the seed and compares with `models/tier_b/arrhythmia/golden.npz`, so the
committed windows can be shown to be this generator's output.
"""

import numpy as np

FS = 250
WIN_S = 10
WIN = FS * WIN_S

GOLDEN_SEED = 20261014
KINDS = (
    "sinus_60",
    "sinus_95_wander",
    "irregular_no_p_wave",
    "emg_noise",
    "brownian_drift",
    "flat_line",
    "huge_spikes",
    "dc_offset_mains",
    "inverted_polarity",
    "clipped_adc",
)
_WAVES = ((-0.16, 0.025, 0.12), (-0.025, 0.010, -0.12), (0.0, 0.012, 1.0), (0.028, 0.012, -0.2), (0.26, 0.055, 0.30))


def _beats(times: np.ndarray, gain: float = 1.0, p_wave: bool = True) -> np.ndarray:
    t = np.arange(WIN) / FS
    x = np.zeros(WIN)
    for tb in times:
        for k, (off, sigma, amp) in enumerate(_WAVES):
            if k == 0 and not p_wave:
                continue
            x += gain * amp * np.exp(-0.5 * ((t - (tb + off)) / sigma) ** 2)
    return x


def _regular(rng: np.random.Generator, bpm: float) -> np.ndarray:
    rr = 60.0 / bpm
    times = np.cumsum(np.clip(rng.normal(rr, 0.02, 20), 0.3, None)) - rr * rng.uniform(0.0, 1.0)
    return times[(times > -0.3) & (times < WIN_S + 0.3)]


def synthetic_windows(seed: int = GOLDEN_SEED) -> tuple[np.ndarray, tuple[str, ...]]:
    """Ten synthetic raw windows (mV, 250 Hz). Chosen to drive activations negative and large."""
    rng = np.random.default_rng(seed)
    t = np.arange(WIN) / FS
    out: list[np.ndarray] = []
    out.append(_beats(_regular(rng, 60)) + rng.normal(0, 0.02, WIN))
    out.append(_beats(_regular(rng, 95)) + 0.4 * np.sin(2 * np.pi * 0.3 * t + 0.7) + rng.normal(0, 0.03, WIN))
    irr = np.cumsum(rng.uniform(0.35, 1.3, 30))
    out.append(_beats(irr[irr < WIN_S + 0.3], p_wave=False) + 0.03 * np.sin(2 * np.pi * 6.0 * t) + rng.normal(0, 0.03, WIN))
    out.append(_beats(_regular(rng, 70)) + rng.normal(0, 0.35, WIN))
    out.append(2.0 * np.cumsum(rng.normal(0, 0.05, WIN)) / np.sqrt(FS) * 4.0)
    out.append(rng.normal(0, 1e-4, WIN))
    spikes = _beats(_regular(rng, 75)) + rng.normal(0, 0.02, WIN)
    for i in rng.integers(100, WIN - 100, 3):
        spikes[i : i + 3] += 50.0
    out.append(spikes)
    out.append(_beats(_regular(rng, 80)) + 5.0 + 0.5 * np.sin(2 * np.pi * 50.0 * t) + rng.normal(0, 0.02, WIN))
    out.append(_beats(_regular(rng, 65), gain=-1.2) + rng.normal(0, 0.02, WIN))
    out.append(np.clip(_beats(_regular(rng, 100), gain=3.0) + rng.normal(0, 0.05, WIN), -1.5, 1.5))
    return np.stack(out).astype(np.float32), KINDS
