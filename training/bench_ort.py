#!/usr/bin/env python
"""CPU latency and memory of the FP32 rhythm head under ONNX Runtime (M3 exit gate, item 3). Dev tool.

One 10 s window per call (batch 1), one thread, warm. The windows are the ten seeded synthetic
ones of golden.npz (already filtered and normalised), so no recording is needed and nothing is
committed. Peak RSS is the operating system's high-water mark of THIS process: the interpreter,
numpy, ONNX Runtime, the model and the loop. Run it alone on a quiet machine.

    python bench_ort.py --onnx OUT_DIR/tiny_fp32.onnx [--n 3000] [--json result.json]

The model is the network only: the band-pass and normalisation that precede it in the labeller
are not in this number (the backend's numpy labeller, which has no ONNX Runtime, is timed whole).
"""

import argparse
import hashlib
import json
import pathlib
import platform
import resource
import subprocess
import sys
import time

import numpy as np
import onnxruntime as ort

WARMUP = 200
WINDOWS_PER_MINUTE = 6  # non-overlapping 10 s windows


def _cpu() -> str:
    if platform.system() == "Darwin":
        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, check=False
        )
        if out.stdout.strip():
            return out.stdout.strip()
    return platform.processor() or platform.machine()


def main() -> None:
    here = pathlib.Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onnx", required=True, type=pathlib.Path)
    ap.add_argument(
        "--golden", type=pathlib.Path, default=here.parent / "models" / "tier_b" / "arrhythmia" / "golden.npz"
    )
    ap.add_argument("--n", type=int, default=3000, help="timed calls after the warm-up")
    ap.add_argument("--json", type=pathlib.Path)
    args = ap.parse_args()

    windows = np.load(args.golden)["x_norm"].astype(np.float32)[:, None, None, :]
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    session = ort.InferenceSession(str(args.onnx), opts, providers=["CPUExecutionProvider"])

    def run(i: int) -> None:
        k = i % len(windows)
        session.run(None, {"ecg": windows[k : k + 1]})

    for i in range(WARMUP):
        run(i)
    ms = np.empty(args.n)
    for i in range(args.n):
        t0 = time.perf_counter_ns()
        run(i)
        ms[i] = (time.perf_counter_ns() - t0) / 1e6
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS, KiB on Linux
    peak_mb = peak / 1e6 if platform.system() == "Darwin" else peak / 1e3
    p50, p95, p99 = (float(v) for v in np.percentile(ms, [50, 95, 99]))
    res = {
        "model": args.onnx.name,
        "sha256": hashlib.sha256(args.onnx.read_bytes()).hexdigest(),
        "runtime": f"onnxruntime {ort.__version__}, CPUExecutionProvider",
        "threads": 1,
        "batch": 1,
        "warmup_calls": WARMUP,
        "timed_calls": args.n,
        "ms_per_window": {"p50": p50, "p95": p95, "p99": p99, "mean": float(ms.mean()), "max": float(ms.max())},
        "ms_per_patient_minute": {"p50": p50 * WINDOWS_PER_MINUTE, "p95": p95 * WINDOWS_PER_MINUTE},
        "peak_rss_mb": round(peak_mb, 1),
        "cpu": _cpu(),
        "os": platform.platform(),
        "python": sys.version.split()[0],
    }
    print(json.dumps(res, indent=1))
    if args.json:
        args.json.write_text(json.dumps(res, indent=1) + "\n")


if __name__ == "__main__":
    main()
