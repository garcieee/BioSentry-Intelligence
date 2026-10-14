"""Deterministic synthetic ECG + PPG + chest accelerometer with a known breathing rate.

Stands in for the CP3b generator until it lands. The three channels share beat times; each
carries its own breathing modulation so a test can make one of them disagree: R-peak amplitude
for the ECG, pulse amplitude for the PPG, chest motion for the accelerometer. Everything comes
from one seed. Not a physiological simulator.
"""

from dataclasses import dataclass

import numpy as np

# (offset s, sigma s, amplitude mV) of the P, Q, R, S and T waves of a normal beat
_NORMAL = (
    (-0.16, 0.025, 0.12),
    (-0.025, 0.010, -0.12),
    (0.0, 0.012, 1.0),
    (0.028, 0.012, -0.2),
    (0.26, 0.055, 0.30),
)


@dataclass(frozen=True, slots=True)
class SynthVitals:
    ecg_fs: float
    ecg: tuple[float, ...]
    ppg_fs: float
    ppg: tuple[float, ...]
    accel_fs: float
    accel: tuple[float, ...]
    rr_bpm: float  # the breathing rate the channels were built from
    pi_percent: float  # truth perfusion index: 100 x pulse amplitude / DC


def synth_vitals(
    *,
    duration_s: float = 64.0,
    hr_bpm: float = 72.0,
    rr_bpm: float = 15.0,
    ecg_rr_bpm: float | None = None,
    ppg_rr_bpm: float | None = None,
    accel_rr_bpm: float | None = None,
    ppg_dc: float = 1000.0,
    ppg_ac: float = 12.0,
    depth: float = 0.2,
    ppg_baseline: float = 0.004,
    accel_amp: float = 0.05,
    noise: float = 1.0,
    ecg_fs: float = 250.0,
    ppg_fs: float = 100.0,
    accel_fs: float = 25.0,
    seed: int = 0,
) -> SynthVitals:
    rng = np.random.default_rng(seed)
    f_ecg = (ecg_rr_bpm if ecg_rr_bpm is not None else rr_bpm) / 60.0
    f_ppg = (ppg_rr_bpm if ppg_rr_bpm is not None else rr_bpm) / 60.0
    f_acc = (accel_rr_bpm if accel_rr_bpm is not None else rr_bpm) / 60.0
    beats: list[float] = []
    t = 0.6
    while t < duration_s - 0.8:
        beats.append(t)
        t += float(np.clip(rng.normal(60.0 / hr_bpm, 0.02), 0.4, 1.6))

    n = round(duration_s * ecg_fs)
    axis = np.arange(n) / ecg_fs
    ecg = 0.1 * np.sin(2 * np.pi * f_ecg * axis + 0.7) + rng.normal(0.0, 0.02 * noise, n)
    for tb in beats:
        gain = 1.0 + depth * np.sin(2 * np.pi * f_ecg * tb)
        for off, sigma, amp in _NORMAL:
            ecg += gain * amp * np.exp(-0.5 * ((axis - (tb + off)) / sigma) ** 2)

    m = round(duration_s * ppg_fs)
    paxis = np.arange(m) / ppg_fs
    ppg = (
        ppg_dc
        + ppg_baseline * ppg_dc * np.sin(2 * np.pi * f_ppg * paxis)
        + rng.normal(0.0, 0.25 * noise, m)
    )
    for tb in beats:
        gain = 1.0 + depth * np.sin(2 * np.pi * f_ppg * tb + 1.0)
        tp = tb + 0.25  # pulse transit delay
        ppg += gain * ppg_ac * np.exp(-0.5 * ((paxis - tp) / 0.09) ** 2)
        ppg += gain * ppg_ac * 0.3 * np.exp(-0.5 * ((paxis - (tp + 0.3)) / 0.10) ** 2)

    k = round(duration_s * accel_fs)
    aaxis = np.arange(k) / accel_fs
    accel = accel_amp * np.sin(2 * np.pi * f_acc * aaxis + 0.3) + rng.normal(0.0, 0.01 * noise, k)

    return SynthVitals(
        ecg_fs,
        tuple(float(v) for v in ecg),
        ppg_fs,
        tuple(float(v) for v in ppg),
        accel_fs,
        tuple(float(v) for v in accel),
        rr_bpm,
        100.0 * ppg_ac / ppg_dc,
    )
