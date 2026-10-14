"""Seeded vital signs for one scripted patient (PLAN, Innovation brief: CP3 generator).

Layers, each with its own independent random stream per patient:

  1. a shared latent severity (slow OU process) that couples the four vitals;
  2. a per-vital path from the script's start to its end level, plus slow wander and a small
     circadian term;
  3. measurement noise;
  4. a semi-Markov dropout layer for the patch (short random losses, then the script's
     scripted gaps and trailing signal loss), applied as NaN end to end.

The last usable reading of every vital is pinned to the script's end level, so the scripted
NEWS2 holds for any seed. Nothing is filled in: a lost minute is NaN, and a 15-minute bin
with too few usable minutes has no median (a gap, never zero).
"""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .scenarios import DEVICE_VITALS, Scenario, Vital

MINUTES = 360  # six hours at one sample per minute; index 359 is as_of
BIN_MINUTES = 15
BINS = MINUTES // BIN_MINUTES  # 24
SPARK_BINS = 12  # the sparkline is the last three hours
MIN_VALID_PER_BIN = 8  # fewer usable minutes than this: the bin has no median

# Generator clamps (PLAN CP3 data): keep every value physically believable.
CLAMPS: dict[Vital, tuple[float, float]] = {
    "heart_rate": (30.0, 200.0),
    "respiratory_rate": (6.0, 40.0),
    "spo2": (78.0, 100.0),
    "temperature": (34.5, 40.5),
}
COUPLING: dict[Vital, float] = {
    "heart_rate": 1.2,
    "respiratory_rate": 0.35,
    "spo2": -0.25,
    "temperature": 0.03,
}
MEASUREMENT_NOISE: dict[Vital, float] = {
    "heart_rate": 0.8,
    "respiratory_rate": 0.4,
    "spo2": 0.25,
    "temperature": 0.02,
}
CIRCADIAN_AMPLITUDE: dict[Vital, float] = {
    "heart_rate": 2.0,
    "respiratory_rate": 0.3,
    "spo2": 0.0,
    "temperature": 0.12,
}
LOCAL_HOUR_AT_AS_OF = 15.0  # as_of 07:00Z is 15:00 in Manila (UTC+8, no DST)
PIN_RAMP_MIN = 30  # the last 30 usable minutes ease onto the scripted end level
AF_IRREGULARITY_BPM = 6.0
MEAN_MINUTES_BETWEEN_DROPOUTS = 150
MAX_RANDOM_LOSS_PER_BIN = 6  # random dropouts alone never null a bin

# One independent stream per layer (and per vital within a layer).
_LAYER_LATENT = 0
_LAYER_WANDER = 1  # + vital index
_LAYER_MEASURE = 10  # + vital index
_LAYER_DROPOUT = 20
_LAYER_LATENCY = 21

Series = NDArray[np.float64]


def _stream(seed: int, patient_index: int, layer: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([seed, patient_index, layer]))


def _ou(rng: np.random.Generator, n: int, tau: float, sd: float) -> Series:
    """Ornstein-Uhlenbeck (AR(1)) path with stationary standard deviation `sd`."""
    phi = math.exp(-1.0 / tau)
    innovation = sd * math.sqrt(1.0 - phi * phi)
    draws = rng.standard_normal(n + 1)
    out = np.empty(n)
    previous = sd * float(draws[0])
    for i in range(n):
        previous = phi * previous + innovation * float(draws[i + 1])
        out[i] = previous
    return out


def _shape(trajectory: str, n: int) -> Series:
    u = np.linspace(0.0, 1.0, n)
    if trajectory == "deteriorating":
        return u**2  # accelerates late
    if trajectory == "improving":
        return 1.0 - (1.0 - u) ** 2  # eases early, then plateaus
    return u


def _circadian(amplitude: float, n: int) -> Series:
    hours = (LOCAL_HOUR_AT_AS_OF - (n - 1 - np.arange(n)) / 60.0) % 24.0
    return amplitude * np.sin(2.0 * math.pi * (hours - 15.0) / 24.0)


def _dropout_mask(rng: np.random.Generator, n: int) -> NDArray[np.bool_]:
    """Semi-Markov patch contact: True = usable. Short random losses, at most 6 per bin."""
    usable = np.ones(n, dtype=np.bool_)
    i = int(rng.geometric(1.0 / MEAN_MINUTES_BETWEEN_DROPOUTS))
    while i < n:
        length = int(rng.integers(1, 5))  # 1 to 4 minutes
        usable[i : i + length] = False
        i += length + int(rng.geometric(1.0 / MEAN_MINUTES_BETWEEN_DROPOUTS))
    for b in range(BINS):
        lo, hi = b * BIN_MINUTES, (b + 1) * BIN_MINUTES
        lost = np.flatnonzero(~usable[lo:hi])
        for extra in lost[MAX_RANDOM_LOSS_PER_BIN:]:
            usable[lo + int(extra)] = True
    return usable


def _bin_medians(minutes: Series) -> tuple[float | None, ...]:
    out: list[float | None] = []
    for b in range(BINS):
        chunk = minutes[b * BIN_MINUTES : (b + 1) * BIN_MINUTES]
        valid = chunk[~np.isnan(chunk)]
        out.append(round(float(np.median(valid)), 1) if valid.size >= MIN_VALID_PER_BIN else None)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Latest:
    value: float
    minute: int  # index into the minute series; MINUTES - 1 is as_of


@dataclass(frozen=True, slots=True)
class PatientSignals:
    minutes: dict[Vital, Series]  # NaN = no usable sample
    bins: dict[Vital, tuple[float | None, ...]]  # 24 medians, None = gap
    latest: dict[Vital, Latest | None]
    signal_quality: int  # percent of the last hour the patch delivered
    last_update_s: int  # seconds from the last patch sample to as_of


def simulate(scenario: Scenario, seed: int, patient_index: int) -> PatientSignals | None:
    """The six hours up to as_of, or None for a patient with no patch applied."""
    if scenario.plans is None:
        return None
    n = MINUTES
    z = _ou(_stream(seed, patient_index, _LAYER_LATENT), n, tau=45.0, sd=1.0)
    patch = _dropout_mask(_stream(seed, patient_index, _LAYER_DROPOUT), n)
    if scenario.signal_lost_min > 0:
        patch[n - scenario.signal_lost_min :] = False

    minutes: dict[Vital, Series] = {}
    latest: dict[Vital, Latest | None] = {}
    for v_index, vital in enumerate(DEVICE_VITALS):
        plan = scenario.plans[vital]
        wander = _ou(_stream(seed, patient_index, _LAYER_WANDER + v_index), n, 20.0, plan.noise)
        measure_rng = _stream(seed, patient_index, _LAYER_MEASURE + v_index)
        noise = MEASUREMENT_NOISE[vital]
        if vital == "heart_rate" and scenario.irregular_hr:
            noise = math.hypot(noise, AF_IRREGULARITY_BPM)
        raw = (
            plan.start
            + (plan.end - plan.start) * _shape(scenario.trajectory, n)
            + _circadian(CIRCADIAN_AMPLITUDE[vital], n)
            + wander
            + COUPLING[vital] * z
            + noise * measure_rng.standard_normal(n)
        )

        usable = patch.copy()
        for gap in scenario.gaps:
            if vital in gap.vitals:
                for b in gap.bins:
                    usable[b * BIN_MINUTES : (b + 1) * BIN_MINUTES] = False

        valid_idx = np.flatnonzero(usable)
        if valid_idx.size == 0:
            minutes[vital] = np.full(n, np.nan)
            latest[vital] = None
            continue
        pin = int(valid_idx[-1])
        ramp = np.clip((np.arange(n) - (pin - PIN_RAMP_MIN)) / PIN_RAMP_MIN, 0.0, 1.0)
        series = raw - (raw[pin] - plan.end) * ramp
        low, high = CLAMPS[vital]
        series = np.clip(series, low, high)
        series[pin] = plan.end  # the scripted current reading, exactly
        series[~usable] = np.nan
        minutes[vital] = series
        latest[vital] = Latest(float(plan.end), pin)

    last_patch = int(np.flatnonzero(patch)[-1]) if patch.any() else -1
    latency = int(_stream(seed, patient_index, _LAYER_LATENCY).integers(1, 10))
    last_hour = patch[n - 60 :]
    return PatientSignals(
        minutes=minutes,
        bins={v: _bin_medians(minutes[v]) for v in DEVICE_VITALS},
        latest=latest,
        signal_quality=round(100 * float(last_hour.mean())),
        last_update_s=(n - 1 - last_patch) * 60 + latency,
    )
