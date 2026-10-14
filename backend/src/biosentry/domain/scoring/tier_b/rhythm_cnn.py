"""Tier B arrhythmia head: the M3b tiny rhythm CNN's forward pass in numpy.

The model (`models/tier_b/arrhythmia/`, status research) labels one 10 s, 250 Hz, single-lead
window as N, AF, Other or Noisy. This module runs it with numpy only, FP32 or INT8 (static QDQ
fake-quantisation, the arithmetic of the ONNX INT8 model), so the backend needs no ONNX Runtime
or MindSpore. Parity with ONNX Runtime is pinned by `models/tier_b/arrhythmia/golden.npz`.

I1: a window is classified only when all 2500 samples are present and usable; anything else is
`NotComputed`. Nothing is filled, interpolated or resampled, and a gap is never counted as normal.
A window the model calls Noisy is a refusal too, so the AF burden denominator holds accepted
windows only. This is a research model (card, registry): it displays, it does not rank (Tier B
never ranks, I3) or diagnose, and it has not been trained or tuned on BioSentry patients (I5).
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np
from numpy.typing import NDArray

from biosentry.schemas import Provenance, ProvenanceSource, Tier

from ...computed import Computed, NotComputed, Result

MODEL_ID: Final = "tier_b/arrhythmia"
MODEL_VERSION: Final = "0.1.0-spike"
FS: Final = 250
WINDOW: Final = 2500  # 10 s at 250 Hz
CLASSES: Final = ("N", "AF", "Other", "Noisy")
N_CONVS: Final = 8
INT8_MIN: Final = -128
INT8_MAX: Final = 127

Precision = Literal["fp32", "int8"]
Float32Array = NDArray[np.float32]
Float64Array = NDArray[np.float64]

_REPO_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_WEIGHTS: Final = _REPO_ROOT / "models" / "tier_b" / "arrhythmia" / "weights.npz"


@dataclass(frozen=True, slots=True)
class Weights:
    """The arrays of `weights.npz`, validated on load (names, not contents, are checked here;
    the registry's sha256 pins the contents)."""

    arrays: Mapping[str, NDArray[Any]]

    def __getitem__(self, name: str) -> NDArray[Any]:
        return self.arrays[name]

    @property
    def threshold(self) -> float:
        return float(self.arrays["af_threshold"][0])


def load_weights(path: Path = DEFAULT_WEIGHTS) -> Weights:
    with np.load(path, allow_pickle=False) as data:
        arrays = {name: data[name] for name in data.files}
    required = {"sos", "conv_stride", "conv_pad", "conv_dilation", "fp32_fc_w", "int8_fc_w"}
    missing = required - set(arrays)
    if missing:
        raise ValueError(f"weights file lacks {sorted(missing)}")
    if int(arrays["window"][0]) != WINDOW or int(arrays["fs"][0]) != FS:
        raise ValueError("weights were exported for a different window or sampling rate")
    return Weights(arrays)


# --- preprocessing ------------------------------------------------------------------------


def sos_filter(sos: Float64Array, x: Float64Array) -> Float64Array:
    """Causal second-order-section filter, direct form II transposed, zero initial state."""
    y = np.asarray(x, dtype=np.float64)
    for b0, b1, b2, _a0, a1, a2 in sos.tolist():
        out = np.empty_like(y)
        z1 = z2 = 0.0
        for i, xi in enumerate(y.tolist()):
            yi = b0 * xi + z1
            z1 = b1 * xi - a1 * yi + z2
            z2 = b2 * xi - a2 * yi
            out[i] = yi
        y = out
    return y


def band_pass(window: Float32Array, weights: Weights) -> Float32Array:
    """0.5-40 Hz causal band-pass of one window, as trained (zero state at the window start)."""
    filtered = sos_filter(weights["sos"].astype(np.float64), window.astype(np.float64))
    return np.asarray(filtered, dtype=np.float32)


def robust_normalise(filtered: Float32Array, weights: Weights) -> Float32Array:
    """Median/MAD normalisation of one window, clipped: the scale the network was trained on."""
    med = np.median(filtered)
    mad = np.median(np.abs(filtered - med)) * weights["mad_scale"][0]
    scaled = (filtered - med) / (mad + weights["norm_eps"][0])
    clip = weights["norm_clip"][0]
    return np.asarray(np.clip(scaled, -clip, clip), dtype=np.float32)


def preprocess(window: Sequence[float], weights: Weights) -> Float32Array:
    raw = np.asarray(window, dtype=np.float32)
    return robust_normalise(band_pass(raw, weights), weights)


# --- forward passes -----------------------------------------------------------------------


def _conv1d(
    x: Float32Array, w: Float32Array, b: Float32Array, stride: int, pad: int, dilation: int
) -> Float32Array:
    """Cross-correlation, as ONNX Conv: x (N, Cin, L), w (Cout, Cin, K), zero padding."""
    n, _, length = x.shape
    cout, _, k = w.shape
    padded = np.pad(x, ((0, 0), (0, 0), (pad, pad)))
    out_len = (length + 2 * pad - dilation * (k - 1) - 1) // stride + 1
    y = np.zeros((n, cout, out_len), dtype=np.float32)
    for tap in range(k):
        start = tap * dilation
        taken = padded[:, :, start : start + stride * (out_len - 1) + 1 : stride]
        y += np.einsum("oc,ncl->nol", w[:, :, tap], taken, optimize=True)
    return y + b[None, :, None]


def forward_fp32(
    x: Float32Array, weights: Weights, trace: list[Float32Array] | None = None
) -> Float32Array:
    """Logits (N, 4) for normalised windows x (N, 2500). `trace` collects pre-ReLU outputs."""
    h = x.astype(np.float32)[:, None, :]
    stride, pad, dilation = (weights[k] for k in ("conv_stride", "conv_pad", "conv_dilation"))
    for i in range(N_CONVS):
        pre = _conv1d(
            h,
            weights[f"fp32_conv{i + 1}_w"].astype(np.float32),
            weights[f"fp32_conv{i + 1}_b"].astype(np.float32),
            int(stride[i]),
            int(pad[i]),
            int(dilation[i]),
        )
        if trace is not None:
            trace.append(pre)
        h = np.maximum(pre, 0.0)
    pooled = np.concatenate([h.mean(axis=-1), h.max(axis=-1)], axis=1)
    fc_w = weights["fp32_fc_w"].astype(np.float32)
    fc_b = weights["fp32_fc_b"].astype(np.float32)
    return np.asarray(pooled @ fc_w.T + fc_b, dtype=np.float32)


def _quantise(x: Float32Array, scale: float, zero_point: int) -> Float32Array:
    """QuantizeLinear to int8 (round half to even, saturating), as float for the next step."""
    q = np.rint(x / np.float32(scale)) + zero_point
    return np.asarray(np.clip(q, INT8_MIN, INT8_MAX), dtype=np.float32)


def _dequantise(q: Float32Array, scale: float, zero_point: int) -> Float32Array:
    return np.asarray((q - np.float32(zero_point)) * np.float32(scale), dtype=np.float32)


def _fake_quant(x: Float32Array, scale: float, zero_point: int) -> Float32Array:
    return _dequantise(_quantise(x, scale, zero_point), scale, zero_point)


def forward_int8(x: Float32Array, weights: Weights) -> Float32Array:
    """Logits (N, 4) of the INT8 QDQ model: activations and weights quantised as exported.

    The ReLU is the clip of each activation quantiser (zero point -128), as in the exported
    graph; weights and biases are dequantised per output channel; the logits are quantised too.
    """
    in_scale = float(weights["int8_input_scale"][0])
    in_zero = int(weights["int8_input_zero_point"][0])
    h = _fake_quant(x.astype(np.float32)[:, None, :], in_scale, in_zero)
    stride, pad, dilation = (weights[k] for k in ("conv_stride", "conv_pad", "conv_dilation"))
    act_scale, act_zero = weights["int8_act_scale"], weights["int8_act_zero_point"]
    for i in range(N_CONVS):
        w = weights[f"int8_conv{i + 1}_w"].astype(np.float32)
        w = w * weights[f"int8_conv{i + 1}_w_scale"].astype(np.float32)[:, None, None]
        b = weights[f"int8_conv{i + 1}_b"].astype(np.float32)
        b = b * weights[f"int8_conv{i + 1}_b_scale"].astype(np.float32)
        y = _conv1d(h, w, b, int(stride[i]), int(pad[i]), int(dilation[i]))
        h = _fake_quant(y, float(act_scale[i]), int(act_zero[i]))
    last_scale, last_zero = float(act_scale[-1]), int(act_zero[-1])
    avg = _fake_quant(
        h.mean(axis=-1),
        float(weights["int8_avg_scale"][0]),
        int(weights["int8_avg_zero_point"][0]),
    )
    peak = _fake_quant(h.max(axis=-1), last_scale, last_zero)
    cat = _fake_quant(
        np.concatenate([avg, peak], axis=1),
        float(weights["int8_cat_scale"][0]),
        int(weights["int8_cat_zero_point"][0]),
    )
    fc_w = weights["int8_fc_w"].astype(np.float32)
    fc_w = fc_w * weights["int8_fc_w_scale"].astype(np.float32)[:, None]
    fc_b = weights["int8_fc_b"].astype(np.float32) * weights["int8_fc_b_scale"].astype(np.float32)
    logits = cat @ fc_w.T + fc_b
    return _fake_quant(
        logits.astype(np.float32),
        float(weights["int8_logit_scale"][0]),
        int(weights["int8_logit_zero_point"][0]),
    )


def logits(x: Float32Array, weights: Weights, precision: Precision = "fp32") -> Float32Array:
    return forward_fp32(x, weights) if precision == "fp32" else forward_int8(x, weights)


def softmax(z: Float32Array) -> Float32Array:
    shifted = z - z.max(axis=1, keepdims=True)
    e = np.exp(shifted)
    return np.asarray(e / e.sum(axis=1, keepdims=True), dtype=np.float32)


# --- the labeller -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RhythmProbabilities:
    n: float
    af: float
    other: float
    noisy: float


class RhythmLabeller:
    """`WindowLabeller` for the rhythm head: "af", "normal" or "other", or a refusal.

    A window is refused (`NotComputed`) when it is not exactly 2500 samples, when any sample is
    unusable or not finite (the network is never given a gap), and when the model calls it
    Noisy. AF is p(AF) >= the operating point (0.20, chosen on CinC validation only) among
    accepted windows; otherwise normal or other by the larger probability.
    """

    id = MODEL_ID

    def __init__(self, weights: Weights, precision: Precision = "fp32") -> None:
        self._weights = weights
        self._precision: Precision = precision

    def probabilities(
        self, samples: Sequence[float], usable: Sequence[bool]
    ) -> RhythmProbabilities | NotComputed:
        if len(samples) != WINDOW or len(usable) != WINDOW:
            return NotComputed("window_is_not_10s_at_250hz")
        if not all(usable) or not all(math.isfinite(s) for s in samples):
            return NotComputed("incomplete_window")
        x = preprocess(samples, self._weights)[None, :]
        p = softmax(logits(x, self._weights, self._precision))[0]
        return RhythmProbabilities(float(p[0]), float(p[1]), float(p[2]), float(p[3]))

    def label(self, samples: Sequence[float], usable: Sequence[bool]) -> str | NotComputed:
        got = self.probabilities(samples, usable)
        if isinstance(got, NotComputed):
            return got
        probabilities = (got.n, got.af, got.other, got.noisy)
        if int(np.argmax(probabilities)) == CLASSES.index("Noisy"):
            return NotComputed("noisy_window")
        if got.af >= self._weights.threshold:
            return "af"
        return "normal" if got.n >= got.other else "other"


def model_provenance(base: Provenance) -> Provenance:
    """`base` re-stamped as this model's output: source model, tier B, model id and version."""
    return base.model_copy(
        update={
            "source": ProvenanceSource.model,
            "tier": Tier.B,
            "model_id": f"{MODEL_ID}@{MODEL_VERSION}",
        }
    )


# --- burden -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AfBurden:
    burden: float  # AF windows / windows that were labelled, 0..1
    af_windows: int
    labelled_windows: int
    coverage: float  # labelled windows / all windows, 0..1


def af_burden(labels: Sequence[Result[str]]) -> AfBurden | NotComputed:
    """AF windows over labelled windows. A refused window (gap, noise) is in neither count and
    lowers coverage; it is never counted as normal."""
    labelled = [r for r in labels if isinstance(r, Computed)]
    if not labels:
        return NotComputed("no_windows")
    if not labelled:
        return NotComputed("no_labelled_windows")
    af = sum(1 for r in labelled if r.value == "af")
    return AfBurden(
        burden=af / len(labelled),
        af_windows=af,
        labelled_windows=len(labelled),
        coverage=len(labelled) / len(labels),
    )
