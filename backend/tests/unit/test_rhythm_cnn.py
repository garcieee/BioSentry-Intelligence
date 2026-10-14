"""The rhythm head's numpy forward pass against ONNX Runtime's logits (golden.npz), the labeller's
refusals, and the AF burden.

Parity is asserted on LOGITS, not on labels alone:
  FP32  max |numpy - ONNX Runtime| <= 2e-5 (measured 2.9e-6 on these windows, 3.8e-6 on 720 real
        AFDB windows run once at development time and not committed);
  INT8  the output is quantised in steps of 0.0730, so a difference is a whole number of steps:
        at most one step anywhere (measured: 0 on these windows, one step on 0.5% of 2,880 logits
        of real windows), and at least 90% of logits exactly equal, which a shifted zero point
        or scale cannot satisfy.
The windows are seeded synthetic ones (training/golden_windows.py), never PhysioNet records.
"""

import math
from pathlib import Path

import numpy as np
import pytest
from no_imputation import assert_no_imputation

from biosentry.domain.computed import Computed, NotComputed, Result, Window
from biosentry.domain.scoring.tier_b import rhythm_cnn as rc
from biosentry.domain.scoring.tier_b.interface import label_windows
from biosentry.domain.signals import SignalInput
from biosentry.schemas import Provenance, ProvenanceSource, Tier
from samples import provenance

PROV = Provenance.model_validate(provenance())
GOLDEN = Path(__file__).resolve().parents[3] / "models" / "tier_b" / "arrhythmia" / "golden.npz"
FP32_ATOL = 2e-5
INT8_STEP = 0.0731  # one output quantisation step (scale 0.07296) plus rounding slack


@pytest.fixture(scope="module")
def weights() -> rc.Weights:
    return rc.load_weights()


@pytest.fixture(scope="module")
def golden() -> dict[str, np.ndarray]:
    with np.load(GOLDEN, allow_pickle=False) as data:
        return {name: data[name] for name in data.files}


# --- preprocessing ------------------------------------------------------------------------


def test_band_pass_matches_the_reference_filter(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    got = np.stack([rc.band_pass(w, weights) for w in golden["x_raw"]])
    # float32 filter stages would be off by up to 6.7e-6 here; float64 stages by < 1e-12
    assert np.abs(got - golden["x_filtered"]).max() < 4e-6


def test_normalisation_matches_the_reference_including_the_clip(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    got = np.stack([rc.robust_normalise(w, weights) for w in golden["x_filtered"]])
    assert np.abs(got - golden["x_norm"]).max() < 4e-6
    assert np.abs(golden["x_norm"]).max() == pytest.approx(10.0)  # the clip is exercised
    assert (np.abs(golden["x_norm"]) == 10.0).any(axis=1).sum() >= 3  # in several windows


def test_a_flat_window_is_normalised_through_the_epsilon_not_divided_by_zero(
    weights: rc.Weights,
) -> None:
    flat = np.full(rc.WINDOW, 0.37, dtype=np.float32)
    got = rc.robust_normalise(flat, weights)
    assert np.isfinite(got).all()
    assert (got == 0.0).all()


# --- FP32 forward pass --------------------------------------------------------------------


def test_fp32_logits_match_onnx_runtime_on_a_batch(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    got = rc.forward_fp32(golden["x_norm"], weights)
    assert got.shape == (10, 4)
    assert np.abs(got - golden["logits_fp32"]).max() <= FP32_ATOL


def test_fp32_logits_do_not_depend_on_batch_composition(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    batch = rc.forward_fp32(golden["x_norm"], weights)
    for i in (0, 4, 9):
        one = rc.forward_fp32(golden["x_norm"][i : i + 1], weights)
        assert np.abs(one[0] - batch[i]).max() <= 1e-5


def test_the_golden_windows_drive_activations_negative_and_far_above_six(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    trace: list[np.ndarray] = []
    rc.forward_fp32(golden["x_norm"], weights, trace)
    assert len(trace) == 8
    for i, pre in enumerate(trace, start=1):
        assert pre.min() < -1.0, f"layer {i} never goes negative: the ReLU is not exercised"
        assert pre.max() > 6.0, f"layer {i} never exceeds 6"
    # and past the INT8 quantisers' ranges, so saturation is exercised too
    scales, zeros = weights["int8_act_scale"], weights["int8_act_zero_point"]
    saturated = [
        pre.max() > float(scales[i]) * (127 - int(zeros[i])) for i, pre in enumerate(trace)
    ]
    assert sum(saturated) >= 4


# --- INT8 forward pass --------------------------------------------------------------------


def test_int8_logits_match_onnx_runtime_int8_within_one_output_step(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    got = rc.forward_int8(golden["x_norm"], weights)
    diff = np.abs(got - golden["logits_int8"])
    assert diff.max() <= INT8_STEP
    assert (diff < 1e-6).mean() >= 0.90


def test_int8_logits_are_whole_quantiser_steps(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    got = rc.forward_int8(golden["x_norm"], weights)
    scale = float(weights["int8_logit_scale"][0])
    zero = int(weights["int8_logit_zero_point"][0])
    steps = got / scale + zero
    assert np.allclose(steps, np.rint(steps), atol=1e-3)
    assert steps.min() >= -128
    assert steps.max() <= 127


def test_int8_and_fp32_agree_on_the_class_of_every_golden_window(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    fp32 = rc.forward_fp32(golden["x_norm"], weights).argmax(axis=1)
    int8 = rc.forward_int8(golden["x_norm"], weights).argmax(axis=1)
    assert fp32.tolist() == int8.tolist() == golden["logits_fp32"].argmax(axis=1).tolist()
    assert set(fp32.tolist()) == {0, 1, 2, 3}  # all four classes occur


def test_precision_switch_selects_the_matching_path(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    x = golden["x_norm"][:3]
    assert np.array_equal(rc.logits(x, weights, "fp32"), rc.forward_fp32(x, weights))
    assert np.array_equal(rc.logits(x, weights, "int8"), rc.forward_int8(x, weights))
    assert not np.array_equal(rc.logits(x, weights, "fp32"), rc.logits(x, weights, "int8"))


def test_the_quantiser_rounds_half_to_even_and_saturates_at_both_ends() -> None:
    ties = np.array([0.5, 1.5, 2.5, 3.5, -0.5, -1.5], dtype=np.float32)
    got = rc._quantise(ties, 1.0, 0)
    assert got.tolist() == [0.0, 2.0, 2.0, 4.0, -0.0, -2.0]  # ties to even, as ONNX Runtime
    far = np.array([1e9, -1e9, 126.4, 127.4, -127.6, -128.6], dtype=np.float32)
    assert rc._quantise(far, 1.0, 0).tolist() == [127.0, -128.0, 126.0, 127.0, -128.0, -128.0]
    assert rc._quantise(np.array([0.0], dtype=np.float32), 0.5, -128).tolist() == [-128.0]
    assert rc._dequantise(np.array([-128.0, 127.0], dtype=np.float32), 0.5, -128).tolist() == [
        0.0,
        127.5,
    ]


def test_each_int8_quantiser_uses_its_own_scale_and_zero_point(
    monkeypatch: pytest.MonkeyPatch, weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    calls: list[tuple[float, int]] = []
    original = rc._fake_quant

    def recorder(x: np.ndarray, scale: float, zero_point: int) -> np.ndarray:
        calls.append((scale, zero_point))
        return original(x, scale, zero_point)

    monkeypatch.setattr(rc, "_fake_quant", recorder)
    rc.forward_int8(golden["x_norm"][:2], weights)
    act = [
        (float(s), int(z))
        for s, z in zip(weights["int8_act_scale"], weights["int8_act_zero_point"], strict=True)
    ]

    def pair(name: str) -> tuple[float, int]:
        return float(weights[f"int8_{name}_scale"][0]), int(weights[f"int8_{name}_zero_point"][0])

    # input, the eight conv outputs, average pool, max pool (the last conv's quantiser),
    # concatenation, logits: in this order, nothing skipped, nothing shared by accident
    assert calls == [pair("input"), *act, pair("avg"), act[-1], pair("cat"), pair("logit")]
    assert len({scale for scale, _ in calls}) >= 10  # they are different quantisers


# --- the labeller: classes, operating point, refusals -------------------------------------


@pytest.mark.parametrize("precision", ["fp32", "int8"])
def test_golden_windows_get_the_expected_labels_or_refusals(
    weights: rc.Weights, golden: dict[str, np.ndarray], precision: rc.Precision
) -> None:
    labeller = rc.RhythmLabeller(weights, precision)
    ok = [True] * rc.WINDOW
    got = [labeller.label(w.tolist(), ok) for w in golden["x_raw"]]
    assert got == [
        "normal",  # sinus_60
        "normal",  # sinus_95_wander
        "af",  # irregular_no_p_wave
        NotComputed("noisy_window"),  # emg_noise
        NotComputed("noisy_window"),  # brownian_drift
        NotComputed("noisy_window"),  # flat_line
        NotComputed("noisy_window"),  # huge_spikes
        NotComputed("noisy_window"),  # dc_offset_mains
        "normal",  # inverted_polarity
        "other",  # clipped_adc
    ]


def _fake_logits(monkeypatch: pytest.MonkeyPatch, probabilities: tuple[float, ...]) -> None:
    z = np.log(np.asarray([probabilities], dtype=np.float32))
    monkeypatch.setattr(rc, "logits", lambda x, w, p="fp32": z)


@pytest.mark.parametrize(
    ("probabilities", "expected"),
    [
        ((0.55, 0.21, 0.23, 0.01), "af"),  # p(AF) over the operating point: AF, though N is larger
        ((0.55, 0.19, 0.25, 0.01), "normal"),  # just under it
        ((0.30, 0.19, 0.50, 0.01), "other"),
        ((0.40, 0.2001, 0.3899, 0.01), "af"),  # a hair over the operating point
        ((0.40, 0.1999, 0.3901, 0.01), "normal"),  # a hair under it
        ((0.10, 0.25, 0.10, 0.55), NotComputed("noisy_window")),  # noisy wins over AF
        ((0.30, 0.20, 0.10, 0.40), NotComputed("noisy_window")),  # noisy is the argmax, p < 0.5
        ((0.50, 0.10, 0.05, 0.35), "normal"),  # noisy is a third of the mass but not the argmax
        ((0.10, 0.10, 0.10, 0.70), NotComputed("noisy_window")),
    ],
)
def test_operating_point_and_noisy_rejection(
    monkeypatch: pytest.MonkeyPatch,
    weights: rc.Weights,
    probabilities: tuple[float, ...],
    expected: str | NotComputed,
) -> None:
    _fake_logits(monkeypatch, probabilities)
    got = rc.RhythmLabeller(weights).label([0.0] * rc.WINDOW, [True] * rc.WINDOW)
    assert got == expected


def test_a_window_with_any_unusable_sample_is_refused_whatever_its_value(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    labeller = rc.RhythmLabeller(weights)
    window = golden["x_raw"][0].tolist()
    for index in (0, 1249, rc.WINDOW - 1):
        usable = [True] * rc.WINDOW
        usable[index] = False
        assert labeller.label(window, usable) == NotComputed("incomplete_window")
        garbage = list(window)
        garbage[index] = 1e9  # a finite value under the mask is not read
        assert labeller.label(garbage, usable) == NotComputed("incomplete_window")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_sample_is_refused_even_if_marked_usable(
    weights: rc.Weights, golden: dict[str, np.ndarray], bad: float
) -> None:
    window = golden["x_raw"][0].tolist()
    window[100] = bad
    got = rc.RhythmLabeller(weights).label(window, [True] * rc.WINDOW)
    assert got == NotComputed("incomplete_window")


@pytest.mark.parametrize("length", [0, 1, rc.WINDOW - 1, rc.WINDOW + 1, 3000])
def test_only_a_window_of_exactly_ten_seconds_at_250_hz_is_classified(
    weights: rc.Weights, length: int
) -> None:
    got = rc.RhythmLabeller(weights).label([0.1] * length, [True] * length)
    assert got == NotComputed("window_is_not_10s_at_250hz")


def test_mismatched_mask_length_is_refused_not_broadcast(weights: rc.Weights) -> None:
    got = rc.RhythmLabeller(weights).label([0.0] * rc.WINDOW, [True] * (rc.WINDOW - 1))
    assert got == NotComputed("window_is_not_10s_at_250hz")


def test_probabilities_are_a_distribution_and_follow_the_logits(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    got = rc.RhythmLabeller(weights).probabilities(golden["x_raw"][2].tolist(), [True] * rc.WINDOW)
    assert isinstance(got, rc.RhythmProbabilities)
    total = got.n + got.af + got.other + got.noisy
    assert total == pytest.approx(1.0, abs=1e-5)
    expected = rc.softmax(golden["logits_fp32"][2:3])[0]
    assert (got.n, got.af, got.other, got.noisy) == pytest.approx(tuple(expected), abs=1e-4)


# --- windows through the shared machinery: gaps, provenance, burden -----------------------


def _stream(golden: dict[str, np.ndarray], order: tuple[int, ...]) -> SignalInput:
    samples = tuple(float(v) for i in order for v in golden["x_raw"][i])
    return SignalInput(float(rc.FS), 10.0, samples, (True,) * len(samples))


def test_the_labeller_never_imputes_and_the_mask_alone_decides(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    # sinus, sinus, AF, sinus: the gap covers the two middle windows
    signal = _stream(golden, (0, 1, 2, 8))
    labeller = rc.RhythmLabeller(weights)
    n = signal.samples_per_window
    assert_no_imputation(lambda s: label_windows(labeller, s, PROV), signal, (n, 3 * n))


def test_outputs_carry_the_models_provenance_and_the_windows_coverage(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    signal = _stream(golden, (0, 2, 3))
    results = label_windows(rc.RhythmLabeller(weights), signal, rc.model_provenance(PROV))
    assert [r.value if isinstance(r, Computed) else r for r in results] == [
        "normal",
        "af",
        NotComputed("noisy_window"),
    ]
    first = results[0]
    assert isinstance(first, Computed)
    assert first.provenance.source is ProvenanceSource.model
    assert first.provenance.tier is Tier.B
    assert first.provenance.model_id == "tier_b/arrhythmia@0.1.0-spike"
    assert first.window.coverage == 1.0
    assert PROV.model_id != first.provenance.model_id  # the caller's provenance is not mutated


def test_a_partly_missing_window_is_refused_with_its_reason_and_not_called_normal(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    signal = _stream(golden, (0, 0))
    valid = list(signal.valid)
    for i in range(rc.WINDOW + 100, rc.WINDOW + 300):  # 200 samples of the second window
        valid[i] = False
    gapped = SignalInput(signal.fs, signal.window_s, signal.samples, tuple(valid))
    first, second = label_windows(rc.RhythmLabeller(weights), gapped, PROV)
    assert isinstance(first, Computed)
    assert second == NotComputed("incomplete_window")


def _labelled(*values: str | None) -> list[Result[str]]:
    prov = rc.model_provenance(PROV)
    window = Window(0.0, 10.0, 1.0)
    return [NotComputed("noisy_window") if v is None else Computed(v, prov, window) for v in values]


def test_af_burden_is_af_windows_over_labelled_windows_with_coverage() -> None:
    got = rc.af_burden(_labelled("af", "normal", "af", None, "other", None))
    assert isinstance(got, rc.AfBurden)
    assert (got.af_windows, got.labelled_windows) == (2, 4)
    assert got.burden == pytest.approx(0.5)
    assert got.coverage == pytest.approx(4 / 6)  # refused windows lower coverage, not the burden


def test_a_refused_window_is_never_counted_as_normal_or_as_af() -> None:
    clean = rc.af_burden(_labelled("normal", "normal"))
    with_gaps = rc.af_burden(_labelled("normal", "normal", None, None, None))
    assert isinstance(clean, rc.AfBurden)
    assert isinstance(with_gaps, rc.AfBurden)
    assert clean.burden == with_gaps.burden == 0.0
    assert math.isclose(with_gaps.coverage, 0.4)


def test_af_burden_refuses_when_there_is_nothing_to_divide() -> None:
    assert rc.af_burden([]) == NotComputed("no_windows")
    assert rc.af_burden(_labelled(None, None)) == NotComputed("no_labelled_windows")


# --- loading ------------------------------------------------------------------------------


def test_weights_for_another_window_length_are_rejected(tmp_path: Path) -> None:
    with np.load(rc.DEFAULT_WEIGHTS, allow_pickle=False) as data:
        arrays = {name: data[name] for name in data.files}
    arrays["window"] = np.array([2000], dtype=np.int32)
    path = tmp_path / "other.npz"
    np.savez(path, **arrays)
    with pytest.raises(ValueError, match="different window"):
        rc.load_weights(path)


def test_weights_missing_arrays_are_rejected(tmp_path: Path) -> None:
    with np.load(rc.DEFAULT_WEIGHTS, allow_pickle=False) as data:
        arrays = {name: data[name] for name in data.files if name != "sos"}
    path = tmp_path / "partial.npz"
    np.savez(path, **arrays)
    with pytest.raises(ValueError, match="lacks"):
        rc.load_weights(path)


def test_the_operating_point_is_read_from_the_weights(weights: rc.Weights) -> None:
    assert weights.threshold == pytest.approx(0.20)


# --- the edges of the decision rule and of finiteness -------------------------------------


def test_p_af_exactly_at_the_operating_point_is_af(
    weights: rc.Weights, golden: dict[str, np.ndarray]
) -> None:
    window, usable = golden["x_raw"][2].tolist(), [True] * rc.WINDOW
    p_af = rc.RhythmLabeller(weights).probabilities(window, usable)
    assert isinstance(p_af, rc.RhythmProbabilities)
    # move the operating point onto this window's own p(AF), and just above it
    at = rc.Weights({**weights.arrays, "af_threshold": np.array([p_af.af], dtype=np.float32)})
    above = rc.Weights(
        {
            **weights.arrays,
            "af_threshold": np.array([np.nextafter(np.float32(p_af.af), np.float32(1))]),
        }
    )
    assert rc.RhythmLabeller(at).label(window, usable) == "af"
    assert rc.RhythmLabeller(above).label(window, usable) != "af"


def test_equal_normal_and_other_probabilities_are_called_normal(
    monkeypatch: pytest.MonkeyPatch, weights: rc.Weights
) -> None:
    z = np.array([[2.0, -3.0, 2.0, -5.0]], dtype=np.float32)  # p(N) == p(Other), AF far below
    monkeypatch.setattr(rc, "logits", lambda x, w, p="fp32": z)
    got = rc.RhythmLabeller(weights).label([0.0] * rc.WINDOW, [True] * rc.WINDOW)
    assert got == "normal"


@pytest.mark.parametrize("precision", ["fp32", "int8"])
@pytest.mark.parametrize("value", [1e39, -1e39, 1e300])
def test_a_finite_float64_that_overflows_float32_is_refused_not_labelled(
    weights: rc.Weights, precision: rc.Precision, value: float
) -> None:
    window = [value] * rc.WINDOW  # math.isfinite is True for every sample
    assert all(math.isfinite(v) for v in window)
    got = rc.RhythmLabeller(weights, precision).label(window, [True] * rc.WINDOW)
    assert got == NotComputed("sample_out_of_float32_range")
    assert rc.RhythmLabeller(weights, precision).probabilities(
        window, [True] * rc.WINDOW
    ) == NotComputed("sample_out_of_float32_range")


@pytest.mark.parametrize("precision", ["fp32", "int8"])
def test_a_filter_output_that_overflows_float32_is_refused_with_its_own_reason(
    weights: rc.Weights, precision: rc.Precision
) -> None:
    # 3.3e38 is a valid float32 and not a float64 overflow, but the band-pass of a 10 Hz sine
    # that large peaks at 3.49e38, past the float32 maximum
    t = np.arange(rc.WINDOW) / rc.FS
    window = (3.3e38 * np.sin(2 * np.pi * 10.0 * t)).astype(np.float32).astype(np.float64).tolist()
    got = rc.RhythmLabeller(weights, precision).label(window, [True] * rc.WINDOW)
    assert got == NotComputed("filtered_signal_out_of_float32_range")


@pytest.mark.parametrize("precision", ["fp32", "int8"])
def test_large_but_representable_samples_give_finite_probabilities(
    weights: rc.Weights, precision: rc.Precision
) -> None:
    t = np.arange(rc.WINDOW) / rc.FS
    window = (3.0e38 * np.sin(2 * np.pi * 10.0 * t)).astype(np.float32).astype(np.float64).tolist()
    got = rc.RhythmLabeller(weights, precision).probabilities(window, [True] * rc.WINDOW)
    assert isinstance(got, rc.RhythmProbabilities)
    assert np.isfinite([got.n, got.af, got.other, got.noisy]).all()
    assert got.n + got.af + got.other + got.noisy == pytest.approx(1.0, abs=1e-4)


def test_non_finite_logits_are_refused_not_labelled(
    monkeypatch: pytest.MonkeyPatch, weights: rc.Weights
) -> None:
    z = np.array([[np.nan, 0.0, 0.0, 0.0]], dtype=np.float32)
    monkeypatch.setattr(rc, "logits", lambda x, w, p="fp32": z)
    labeller = rc.RhythmLabeller(weights)
    assert labeller.label([0.1] * rc.WINDOW, [True] * rc.WINDOW) == NotComputed("non_finite_logits")
