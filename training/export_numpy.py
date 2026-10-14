"""Export the trained M3b rhythm head for the backend's numpy forward pass (dev tool).

Reads the FP32 and INT8 ONNX files that `rhythm_head.py export` wrote and writes two files:

  weights.npz  the FP32 weights, the INT8 (QDQ) weights and quantisation parameters, and the
               band-pass coefficients: the one artifact the registry's sha256 pins;
  golden.npz   ten SEEDED SYNTHETIC 10 s windows (generated here, never PhysioNet records),
               the reference pipeline's filtered and normalised values, and ONNX Runtime's
               FP32 and INT8 logits, so CI can check the numpy forward pass without ONNX Runtime.

Run from the repository root with the training environment (training/README.md):

    python training/export_numpy.py --onnx-dir <rhythm_head out dir> --models-dir models/tier_b/arrhythmia

Nothing here reads a patient record: the weights are the model, the windows are generated.
"""

import argparse
import hashlib
import pathlib

import numpy as np
import onnx
import onnxruntime as ort
from onnx import numpy_helper

import rhythm_head as rh
from golden_windows import GOLDEN_SEED, KINDS, synthetic_windows

def _tensor_maps(graph: onnx.GraphProto) -> tuple[dict[str, np.ndarray], dict[str, onnx.NodeProto]]:
    init = {i.name: numpy_helper.to_array(i) for i in graph.initializer}
    dq = {n.output[0]: n for n in graph.node if n.op_type == "DequantizeLinear"}
    return init, dq


def export_arrays(onnx_dir: pathlib.Path) -> dict[str, np.ndarray]:
    a: dict[str, np.ndarray] = {}
    g32 = onnx.load(onnx_dir / "tiny_fp32.onnx").graph
    init32 = {i.name: numpy_helper.to_array(i) for i in g32.initializer}
    convs = [n for n in g32.node if n.op_type == "Conv"]
    assert len(convs) == 8
    stride, pad, dil = [], [], []
    for i, node in enumerate(convs, start=1):
        attr = {x.name: onnx.helper.get_attribute_value(x) for x in node.attribute}
        assert list(attr["kernel_shape"])[0] == 1 and attr["group"] == 1
        stride.append(attr["strides"][1])
        pad.append(attr["pads"][1])
        dil.append(attr["dilations"][1])
        a[f"fp32_conv{i}_w"] = init32[node.input[1]][:, :, 0, :].astype(np.float32)
        a[f"fp32_conv{i}_b"] = init32[node.input[2]].astype(np.float32)
    a["fp32_fc_w"] = init32["fc.weight"].astype(np.float32)
    a["fp32_fc_b"] = init32["fc.bias"].astype(np.float32)
    a["conv_stride"] = np.array(stride, np.int32)
    a["conv_pad"] = np.array(pad, np.int32)
    a["conv_dilation"] = np.array(dil, np.int32)

    g8 = onnx.load(onnx_dir / "tiny_int8.onnx").graph
    init8, dq = _tensor_maps(g8)
    q_after: dict[str, onnx.NodeProto] = {}
    for n in g8.node:
        if n.op_type == "QuantizeLinear":
            q_after.setdefault(n.input[0], n)

    def deq(name: str) -> tuple[np.ndarray, np.ndarray]:
        n = dq[name]
        return init8[n.input[0]], init8[n.input[1]]

    def qparams(node: onnx.NodeProto) -> tuple[float, int]:
        return float(init8[node.input[1]]), int(init8[node.input[2]])

    act_scale, act_zp = [], []
    for i, node in enumerate([n for n in g8.node if n.op_type == "Conv"], start=1):
        wq, ws = deq(node.input[1])
        bq, bs = deq(node.input[2])
        assert wq.dtype == np.int8 and bq.dtype == np.int32
        a[f"int8_conv{i}_w"] = wq[:, :, 0, :].astype(np.int8)
        a[f"int8_conv{i}_w_scale"] = ws.astype(np.float32)
        a[f"int8_conv{i}_b"] = bq.astype(np.int32)
        a[f"int8_conv{i}_b_scale"] = bs.astype(np.float32)
        s, z = qparams(q_after[node.output[0]])
        act_scale.append(s)
        act_zp.append(z)
    a["int8_act_scale"] = np.array(act_scale, np.float32)
    a["int8_act_zero_point"] = np.array(act_zp, np.int32)
    first = next(n for n in g8.node if n.op_type == "QuantizeLinear")
    for key, node in (
        ("input", first),
        ("avg", q_after["/avg/GlobalAveragePool_output_0"]),
        ("cat", q_after["/Concat_output_0"]),
    ):
        s, z = qparams(node)
        a[f"int8_{key}_scale"] = np.array([s], np.float32)
        a[f"int8_{key}_zero_point"] = np.array([z], np.int32)
    gemm = next(n for n in g8.node if n.op_type == "Gemm")
    fwq, fws = deq(gemm.input[1])
    fbq, fbs = deq(gemm.input[2])
    a["int8_fc_w"], a["int8_fc_w_scale"] = fwq.astype(np.int8), fws.astype(np.float32)
    a["int8_fc_b"], a["int8_fc_b_scale"] = fbq.astype(np.int32), fbs.astype(np.float32)
    s, z = qparams(q_after[gemm.output[0]])
    a["int8_logit_scale"] = np.array([s], np.float32)
    a["int8_logit_zero_point"] = np.array([z], np.int32)

    a["sos"] = np.asarray(rh._SOS, np.float64)
    a["fs"] = np.array([rh.FS], np.int32)
    a["window"] = np.array([rh.WIN], np.int32)
    a["norm_clip"] = np.array([10.0], np.float32)
    a["mad_scale"] = np.array([1.4826], np.float32)
    a["norm_eps"] = np.array([1e-6], np.float32)
    a["af_threshold"] = np.array([0.20], np.float32)
    a["classes"] = np.array(rh.CLASSES)
    a["format"] = np.array(["biosentry-rhythm-cnn-1"])
    a["source_onnx_fp32_sha256"] = np.array([hashlib.sha256((onnx_dir / "tiny_fp32.onnx").read_bytes()).hexdigest()])
    a["source_onnx_int8_sha256"] = np.array([hashlib.sha256((onnx_dir / "tiny_int8.onnx").read_bytes()).hexdigest()])
    return a


def golden_arrays(onnx_dir: pathlib.Path) -> dict[str, np.ndarray]:
    raw, kinds = synthetic_windows()
    filtered = np.stack([rh.bandpass(w) for w in raw])
    normed = rh.robust_norm(filtered)
    feed = {"ecg": normed[:, None, None, :].astype(np.float32)}
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    out = {}
    for key, name in (("logits_fp32", "tiny_fp32.onnx"), ("logits_int8", "tiny_int8.onnx")):
        sess = ort.InferenceSession(str(onnx_dir / name), opts, providers=["CPUExecutionProvider"])
        out[key] = sess.run(None, feed)[0].astype(np.float32)
    return {
        "x_raw": raw,
        "x_filtered": filtered.astype(np.float32),
        "x_norm": normed.astype(np.float32),
        "kinds": np.array(kinds),
        "seed": np.array([GOLDEN_SEED], np.int64),
        **out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx-dir", required=True, type=pathlib.Path)
    ap.add_argument("--models-dir", required=True, type=pathlib.Path)
    args = ap.parse_args()
    args.models_dir.mkdir(parents=True, exist_ok=True)
    np.savez(args.models_dir / "weights.npz", **export_arrays(args.onnx_dir))
    np.savez(args.models_dir / "golden.npz", **golden_arrays(args.onnx_dir))
    for name in ("weights.npz", "golden.npz"):
        data = (args.models_dir / name).read_bytes()
        print(f"{name}: {len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
