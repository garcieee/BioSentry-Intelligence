"""The M3b rhythm head's committed artifacts: pinned by sha256, holding weights and nothing else.

`weights.npz` is the artifact the registry pins; `golden.npz` holds seeded SYNTHETIC windows and
reference outputs. Neither may carry a recording (P6), so the array names, shapes and dtypes are
pinned exactly, and the golden windows are regenerated from their seed and compared.
"""

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
import yaml

from biosentry.domain.registry import Registry, RegistryEntry, RegistryStatus

ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = ROOT / "models" / "tier_b" / "arrhythmia"
WEIGHTS = MODEL_DIR / "weights.npz"
GOLDEN = MODEL_DIR / "golden.npz"
CARD = MODEL_DIR / "card.md"

# (out channels, in channels, kernel, stride, padding, dilation) of the eight convolutions
CONVS = (
    (8, 1, 7, 2, 3, 1),
    (16, 8, 5, 2, 2, 1),
    (32, 16, 5, 2, 2, 1),
    (48, 32, 5, 2, 2, 1),
    (64, 48, 5, 2, 2, 1),
    (64, 64, 5, 1, 4, 2),
    (64, 64, 5, 1, 8, 4),
    (64, 64, 5, 1, 16, 8),
)
WINDOW = 2500
N_CLASSES = 4
N_GOLDEN = 10


def _entry() -> RegistryEntry:
    raw = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    return next(m for m in Registry.model_validate(raw).models if m.id == "tier_b/arrhythmia")


def expected_weight_arrays() -> dict[str, tuple[tuple[int, ...], str]]:
    spec: dict[str, tuple[tuple[int, ...], str]] = {}
    for i, (cout, cin, k, _, _, _) in enumerate(CONVS, start=1):
        spec[f"fp32_conv{i}_w"] = ((cout, cin, k), "float32")
        spec[f"fp32_conv{i}_b"] = ((cout,), "float32")
        spec[f"int8_conv{i}_w"] = ((cout, cin, k), "int8")
        spec[f"int8_conv{i}_w_scale"] = ((cout,), "float32")
        spec[f"int8_conv{i}_b"] = ((cout,), "int32")
        spec[f"int8_conv{i}_b_scale"] = ((cout,), "float32")
    spec["fp32_fc_w"] = ((N_CLASSES, 128), "float32")
    spec["fp32_fc_b"] = ((N_CLASSES,), "float32")
    spec["int8_fc_w"] = ((N_CLASSES, 128), "int8")
    spec["int8_fc_w_scale"] = ((N_CLASSES,), "float32")
    spec["int8_fc_b"] = ((N_CLASSES,), "int32")
    spec["int8_fc_b_scale"] = ((N_CLASSES,), "float32")
    spec["int8_act_scale"] = ((8,), "float32")
    spec["int8_act_zero_point"] = ((8,), "int32")
    for key in ("input", "avg", "cat", "logit"):
        spec[f"int8_{key}_scale"] = ((1,), "float32")
        spec[f"int8_{key}_zero_point"] = ((1,), "int32")
    spec.update(
        {
            "conv_stride": ((8,), "int32"),
            "conv_pad": ((8,), "int32"),
            "conv_dilation": ((8,), "int32"),
            "sos": ((2, 6), "float64"),
            "fs": ((1,), "int32"),
            "window": ((1,), "int32"),
            "norm_clip": ((1,), "float32"),
            "mad_scale": ((1,), "float32"),
            "norm_eps": ((1,), "float32"),
            "af_threshold": ((1,), "float32"),
            "classes": ((N_CLASSES,), "<U5"),
            "format": ((1,), "<U22"),
            "source_onnx_fp32_sha256": ((1,), "<U64"),
            "source_onnx_int8_sha256": ((1,), "<U64"),
        }
    )
    return spec


def _golden_generator() -> ModuleType:
    path = ROOT / "training" / "golden_windows.py"
    spec = importlib.util.spec_from_file_location("golden_windows", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the registry pin -------------------------------------------------------------------


def test_the_registry_pins_the_weights_file_by_sha256() -> None:
    digest = hashlib.sha256(WEIGHTS.read_bytes()).hexdigest()
    assert _entry().sha256 == digest, "weights.npz changed: re-export and update the registry"


def test_the_head_is_a_research_entry_with_a_verified_licence_and_three_corpora() -> None:
    entry = _entry()
    assert entry.status is RegistryStatus.research
    assert entry.licence.startswith("https://physionet.org/content/challenge-2017/view-license/")
    assert len(entry.corpus) == 3
    assert entry.valid_until is None
    assert entry.metrics["afdb_external_af_auroc"] > 0.9


# --- weights and nothing else (P6) --------------------------------------------------------


def test_weights_hold_exactly_the_named_arrays_and_no_object_arrays() -> None:
    expected = expected_weight_arrays()
    with np.load(WEIGHTS, allow_pickle=False) as data:
        assert set(data.files) == set(expected)
        for name, (shape, dtype) in expected.items():
            array = data[name]
            assert array.shape == shape, name
            assert array.dtype == np.dtype(dtype), name


def test_the_weight_count_matches_the_folded_network_and_no_array_is_window_sized() -> None:
    with np.load(WEIGHTS, allow_pickle=False) as data:
        fp32 = sum(data[f"fp32_conv{i}_w"].size + data[f"fp32_conv{i}_b"].size for i in range(1, 9))
        fp32 += data["fp32_fc_w"].size + data["fp32_fc_b"].size
        assert fp32 == 88_612
        # the largest array is a 64 x 64 x 5 kernel; nothing here can hold a 10 s recording
        assert max(data[name].size for name in data.files) == 64 * 64 * 5


def test_the_network_geometry_stored_with_the_weights_is_the_one_the_tests_assume() -> None:
    with np.load(WEIGHTS, allow_pickle=False) as data:
        assert data["conv_stride"].tolist() == [c[3] for c in CONVS]
        assert data["conv_pad"].tolist() == [c[4] for c in CONVS]
        assert data["conv_dilation"].tolist() == [c[5] for c in CONVS]
        assert (int(data["fs"][0]), int(data["window"][0])) == (250, WINDOW)
        assert data["classes"].tolist() == ["N", "AF", "Other", "Noisy"]
        assert float(data["af_threshold"][0]) == pytest.approx(0.20)


def test_int8_arrays_use_the_whole_range_sensibly() -> None:
    with np.load(WEIGHTS, allow_pickle=False) as data:
        for i in range(1, 9):
            w = data[f"int8_conv{i}_w"]
            assert w.min() >= -127  # symmetric per-channel weights never use -128
            assert w.max() <= 127
            assert (data[f"int8_conv{i}_w_scale"] > 0).all()
        assert (data["int8_act_scale"] > 0).all()
        assert set(data["int8_act_zero_point"].tolist()) == {-128}  # the ReLU folded into the clip


# --- the parity vectors are synthetic and seeded (P6) -------------------------------------


def test_golden_holds_exactly_ten_windows_and_their_reference_outputs() -> None:
    with np.load(GOLDEN, allow_pickle=False) as data:
        assert set(data.files) == {
            "x_raw",
            "x_filtered",
            "x_norm",
            "kinds",
            "seed",
            "logits_fp32",
            "logits_int8",
        }
        for name in ("x_raw", "x_filtered", "x_norm"):
            assert data[name].shape == (N_GOLDEN, WINDOW)
            assert data[name].dtype == np.float32
        for name in ("logits_fp32", "logits_int8"):
            assert data[name].shape == (N_GOLDEN, N_CLASSES)
            assert data[name].dtype == np.float32
        assert np.isfinite(data["logits_fp32"]).all()
        assert len(data["kinds"]) == N_GOLDEN


def test_golden_windows_are_the_seeded_generators_output_not_recordings() -> None:
    generator = _golden_generator()
    raw, kinds = generator.synthetic_windows(generator.GOLDEN_SEED)
    with np.load(GOLDEN, allow_pickle=False) as data:
        assert int(data["seed"][0]) == generator.GOLDEN_SEED
        assert data["kinds"].tolist() == list(kinds)
        # exp() differs in the last bit between platforms; a recording would differ by orders more
        assert np.allclose(data["x_raw"], raw, atol=1e-5)


# --- the card says what the licence ruling asked it to say --------------------------------


def test_the_card_carries_the_licence_lines_and_the_open_note() -> None:
    card = " ".join(CARD.read_text(encoding="utf-8").split())  # the card is hard-wrapped
    for needle in (
        "Open Data Commons Attribution License v1.0",
        "Anyone can access the files, as long as they conform to the terms of the specified"
        " license.",
        "10.13026/d3hm-sf11",
        "10.13026/C2HS3T",
        "10.13026/C2MW2D",
        "10.13026/C2F305",
        "exclusively for this competition by AliveCor",
        "not cleared for product use",
        "evaluation and development only",
        "never trained, tuned or calibrated on BioSentry patients",
    ):
        assert needle in card, needle
    for slug in ("challenge-2017", "nstdb", "afdb", "mitdb"):
        assert f"https://physionet.org/content/{slug}/view-license/1.0.0/" in card
