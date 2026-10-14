#!/usr/bin/env python
"""Classical RR-irregularity AF baseline for the rhythm head (M3 exit gate, item 1). Dev tool.

The question it answers: on the same windows, does the CNN add anything over a plain rule on the
beat-to-beat interval series? It is numpy only at import time (the commands import
rhythm_head / onnxruntime / wfdb lazily), so backend/tests/unit/test_rr_baseline.py loads and
tests every pure function here without scipy.

Protocol, fixed before AFDB is scored:
  1. R peaks are found in each 10 s window by a plain numpy detector (no state across windows);
  2. a window with fewer than 6 beats, or a median RR outside 0.3-2.0 s, is REFUSED: it is never
     scored as regular (I1, I4), and the refusal rate is reported;
  3. the feature and its threshold are chosen on the CinC 2017 *validation* windows only, with the
     head's own rule (specificity >= 0.95 among accepted windows, then maximum sensitivity);
  4. AFDB is scored once, with record-level bootstrap intervals (1000 resamples, seed 20261014);
  5. MIT-BIH Arrhythmia records of DS1 only are used to check the detector (DS2 is not reachable
     from this file: it is kept for the PVC metric).

    python rr_baseline.py check-detector --data DATA_DIR
    python rr_baseline.py select --out OUT_DIR
    python rr_baseline.py score --data DATA_DIR --out OUT_DIR
"""

import argparse
import json
import math
import pathlib
import sys
from collections.abc import Callable, Iterator, Sequence
from typing import Any, NamedTuple, TypeVar

import numpy as np

T = TypeVar("T")

FS = 250
WINDOW = 2500
MIN_BEATS = 6
MIN_MEDIAN_RR_S = 0.3  # 200 bpm
MAX_MEDIAN_RR_S = 2.0  # 30 bpm
REFRACTORY_S = 0.25
THRESHOLD_FRACTION = 0.25  # of the typical slope-energy peak (median of the five largest)
SEED = 20261014
N_BOOT = 1000
MIN_SPECIFICITY = 0.95  # the head's own rule (rhythm_head.py cmd_opt)
FEATURES = ("nrmssd", "cv", "tpr", "rmad")  # higher = more irregular = more AF-like
MATCH_TOL_S = 0.150  # AAMI EC57 beat matching

# de Chazal inter-patient split of MIT-BIH Arrhythmia; paced records are out by convention. Only
# DS1 is named here on purpose: DS2 is scored once, for the PVC metric, from its own command.
DS1 = (
    "101", "106", "108", "109", "112", "114", "115", "116", "118", "119", "122",
    "124", "201", "203", "205", "207", "208", "209", "215", "220", "223", "230",
)  # fmt: skip
# beat annotation symbols of the database (everything else is a rhythm or comment mark)
BEAT_SYMBOLS = frozenset("NLRBAaJSVrFejnE/fQ?")


# --- the detector -------------------------------------------------------------------------------


def _band_kernel(fs: float, low_hz: float = 5.0, high_hz: float = 15.0, span_s: float = 0.5) -> np.ndarray:
    n = int(round(span_s * fs)) | 1
    t = (np.arange(n) - (n - 1) / 2) / fs

    def low_pass(fc: float) -> np.ndarray:
        return (2 * fc / fs) * np.sinc(2 * fc * t)

    return (low_pass(high_hz) - low_pass(low_hz)) * np.hamming(n)


def _suppress(order: np.ndarray, n: int, radius: int) -> list[int]:
    """Greedy non-maximum suppression: indices in `order` (best first), none within `radius`."""
    taken = np.zeros(n, dtype=bool)
    kept: list[int] = []
    for i in order:
        if taken[i]:
            continue
        kept.append(int(i))
        taken[max(0, i - radius) : i + radius + 1] = True
    return kept


def detect_r_peaks(x: Sequence[float] | np.ndarray, fs: float = FS) -> np.ndarray:
    """R-peak sample indices of one window. Plain Pan-Tompkins-style energy detector.

    Raises ValueError on a non-finite sample: the caller refuses the window (I1), nothing is
    filled. Everything is relative to the window itself, so windows stay independent.
    """
    v = np.asarray(x, dtype=np.float64)
    if v.ndim != 1:
        raise ValueError("one 1-D window at a time")
    if not np.isfinite(v).all():
        raise ValueError("non-finite sample: refuse the window, never fill it (I1)")
    n = v.size
    kernel = _band_kernel(fs)
    half = kernel.size // 2
    if n <= kernel.size:
        return np.zeros(0, dtype=np.int64)
    y = np.convolve(np.pad(v - np.median(v), half, mode="reflect"), kernel, mode="valid")
    slope = np.diff(y, prepend=y[0])
    width = max(int(round(0.15 * fs)), 1)
    energy = np.convolve(np.pad(slope * slope, width // 2, mode="edge"), np.ones(width) / width, "valid")[:n]
    radius = int(round(REFRACTORY_S * fs))
    inner = np.flatnonzero((energy[1:-1] > energy[:-2]) & (energy[1:-1] >= energy[2:])) + 1
    if inner.size == 0:
        return np.zeros(0, dtype=np.int64)
    kept = np.array(_suppress(inner[np.argsort(-energy[inner], kind="stable")], n, radius))
    heights = np.sort(energy[kept])[::-1]
    reference = float(np.median(heights[:5]))
    if reference <= 0.0:
        return np.zeros(0, dtype=np.int64)
    kept = kept[energy[kept] >= THRESHOLD_FRACTION * reference]
    reach = int(round(0.1 * fs))
    refined = np.array(
        [max(0, k - reach) + int(np.argmax(np.abs(y[max(0, k - reach) : k + reach + 1]))) for k in kept],
        dtype=np.int64,
    )
    final = _suppress(refined[np.argsort(-np.abs(y[refined]), kind="stable")], n, radius)
    return np.array(sorted(final), dtype=np.int64)


# --- RR statistics and the refusal rules --------------------------------------------------------


def rr_features(peaks: np.ndarray, fs: float = FS) -> dict[str, float] | str:
    """The four irregularity statistics of one window, or a refusal reason string.

    nrmssd = RMSSD / mean RR; cv = SD / mean RR; tpr = turning-point ratio (a random series has
    2/3); rmad = median |successive difference| / median RR, robust to one or two ectopic beats.
    """
    if peaks.size < MIN_BEATS:
        return "too_few_beats"
    rr = np.diff(peaks.astype(np.float64)) / fs
    median = float(np.median(rr))
    if not MIN_MEDIAN_RR_S <= median <= MAX_MEDIAN_RR_S:
        return "implausible_rate"
    mean = float(rr.mean())
    step = np.diff(rr)
    turning = (rr[1:-1] - rr[:-2]) * (rr[1:-1] - rr[2:]) > 0
    return {
        "nrmssd": float(math.sqrt(float(np.mean(step * step)))) / mean,
        "cv": float(rr.std()) / mean,
        "tpr": float(turning.mean()),
        "rmad": float(np.median(np.abs(step))) / median,
    }


def window_features(window: np.ndarray, fs: float = FS) -> dict[str, float] | str:
    """Detector then statistics; a window with a non-finite sample is refused, never filled."""
    if not np.isfinite(np.asarray(window, dtype=np.float64)).all():
        return "incomplete_window"
    return rr_features(detect_r_peaks(window, fs), fs)


# --- metrics (numpy only) -----------------------------------------------------------------------


def auroc(positive: np.ndarray, score: np.ndarray) -> float:
    """Rank-sum AUROC with tied scores averaged; NaN when one class is missing."""
    pos = np.asarray(positive, dtype=bool)
    s = np.asarray(score, dtype=np.float64)
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    _, inverse, counts = np.unique(s, return_inverse=True, return_counts=True)
    upper = np.cumsum(counts)
    mean_rank = upper - (counts - 1) / 2.0
    ranks = mean_rank[inverse]
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def threshold_for_specificity(positive: np.ndarray, score: np.ndarray, min_specificity: float = MIN_SPECIFICITY) -> float:
    """Smallest t such that 'score >= t' keeps specificity >= min_specificity (so sensitivity is
    maximal under that constraint). Ties are never split."""
    pos = np.asarray(positive, dtype=bool)
    s = np.asarray(score, dtype=np.float64)
    neg = np.sort(s[~pos])
    if neg.size == 0:
        raise ValueError("no negatives: the threshold is undefined")
    candidates = np.unique(s)
    specificity = np.searchsorted(neg, candidates, side="left") / neg.size
    ok = np.flatnonzero(specificity >= min_specificity)
    return float(candidates[ok[0]]) if ok.size else float(np.nextafter(s.max(), np.inf))


def rates(positive: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    """Sensitivity, specificity, PPV; NaN (never 0) where a denominator is empty."""
    pos = np.asarray(positive, dtype=bool)
    pred = np.asarray(predicted, dtype=bool)
    tp, fp = int((pred & pos).sum()), int((pred & ~pos).sum())
    fn, tn = int((~pred & pos).sum()), int((~pred & ~pos).sum())

    def ratio(a: int, b: int) -> float:
        return a / b if b else float("nan")

    return {
        "sensitivity": ratio(tp, tp + fn),
        "specificity": ratio(tn, tn + fp),
        "ppv": ratio(tp, tp + fp),
        "tp": float(tp),
        "fp": float(fp),
        "fn": float(fn),
        "tn": float(tn),
    }


def record_bootstrap(
    records: Sequence[T],
    statistics: Callable[[Sequence[T]], dict[str, float]],
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict[str, dict[str, float]]:
    """Percentile 95% intervals resampling whole records (the unit that shares a patient)."""
    point = statistics(records)
    rng = np.random.default_rng(seed)
    draws: dict[str, list[float]] = {k: [] for k in point}
    for _ in range(n_boot):
        pick = rng.integers(0, len(records), len(records))
        for key, value in statistics([records[i] for i in pick]).items():
            draws[key].append(value)
    out: dict[str, dict[str, float]] = {}
    for key, values in draws.items():
        arr = np.asarray(values, dtype=np.float64)
        finite = arr[np.isfinite(arr)]
        out[key] = {
            "point": point[key],
            "lo": float(np.percentile(finite, 2.5)) if finite.size else float("nan"),
            "hi": float(np.percentile(finite, 97.5)) if finite.size else float("nan"),
            "undefined_draws": float(arr.size - finite.size),
        }
    return out


def match_beats(reference: np.ndarray, detected: np.ndarray, tolerance: float) -> tuple[int, int, int]:
    """(true positives, false positives, false negatives): each reference beat matches at most one
    detection and vice versa, both sorted, within `tolerance` (same unit as the arrays)."""
    i = j = tp = 0
    while i < len(reference) and j < len(detected):
        gap = detected[j] - reference[i]
        if abs(gap) <= tolerance:
            tp += 1
            i += 1
            j += 1
        elif gap < 0:
            j += 1
        else:
            i += 1
    return tp, len(detected) - tp, len(reference) - tp


class Record(NamedTuple):
    """One AFDB record: label 0 N / 1 AF / 2 Other, the head's four probabilities, and the
    baseline score (NaN where the baseline refused the window)."""

    y: np.ndarray
    head_p: np.ndarray
    base_score: np.ndarray


def baseline_stats(
    records: Sequence[Record], head_threshold: float, base_threshold: float
) -> dict[str, float]:
    """Head and baseline on the same windows. A refusal is scored as the lowest value in the
    all-windows AUROC (never as AF) and sits outside the sensitivity, specificity and PPV."""
    parts = list(records)
    y = np.concatenate([p.y for p in parts])
    prob = np.concatenate([p.head_p for p in parts])
    score = np.concatenate([p.base_score for p in parts])
    af = y == 1
    head_ok = prob.argmax(axis=1) != 3
    base_ok = ~np.isnan(score)
    both = head_ok & base_ok
    base_all = np.where(base_ok, score, -np.inf)
    out: dict[str, float] = {
        "head_auroc_all": auroc(af, prob[:, 1]),
        "base_auroc_all": auroc(af, base_all),
        "head_auroc_accepted": auroc(af[head_ok], prob[head_ok, 1]),
        "base_auroc_accepted": auroc(af[base_ok], score[base_ok]),
        "head_auroc_both": auroc(af[both], prob[both, 1]),
        "base_auroc_both": auroc(af[both], score[both]),
        "head_refused": float((~head_ok).mean()),
        "base_refused": float((~base_ok).mean()),
        "both_accepted": float(both.mean()),
    }
    out["delta_auroc_all"] = out["head_auroc_all"] - out["base_auroc_all"]
    out["delta_auroc_both"] = out["head_auroc_both"] - out["base_auroc_both"]
    head_rates = rates(af[head_ok], prob[head_ok, 1] >= head_threshold)
    base_rates = rates(af[base_ok], score[base_ok] >= base_threshold)
    for key in ("sensitivity", "specificity", "ppv"):
        out[f"head_{key}"] = head_rates[key]
        out[f"base_{key}"] = base_rates[key]
        out[f"delta_{key}"] = head_rates[key] - base_rates[key]
    # a descriptive upper bound, not an operating point: the baseline's threshold re-chosen on these
    # very windows to match the head's specificity, so a transferred threshold cannot be blamed
    if (~af[base_ok]).any() and not math.isnan(head_rates["specificity"]):
        t_star = threshold_for_specificity(af[base_ok], score[base_ok], head_rates["specificity"])
        oracle = rates(af[base_ok], score[base_ok] >= t_star)
        out["base_sensitivity_at_head_specificity"] = oracle["sensitivity"]
        out["base_specificity_at_head_specificity"] = oracle["specificity"]
    else:
        out["base_sensitivity_at_head_specificity"] = float("nan")
        out["base_specificity_at_head_specificity"] = float("nan")
    errors_head: list[float] = []
    errors_base: list[float] = []
    for rec in parts:
        truth = float((rec.y == 1).mean())
        ok = rec.head_p.argmax(axis=1) != 3
        if ok.any():
            errors_head.append(abs(float((rec.head_p[ok, 1] >= head_threshold).mean()) - truth))
        okb = ~np.isnan(rec.base_score)
        if okb.any():
            errors_base.append(abs(float((rec.base_score[okb] >= base_threshold).mean()) - truth))
    out["head_burden_mae"] = float(np.mean(errors_head)) if errors_head else float("nan")
    out["base_burden_mae"] = float(np.mean(errors_base)) if errors_base else float("nan")
    return out


# --- commands (data, torch-free; onnxruntime and wfdb are imported where used) ------------------


def _rhythm_head() -> Any:
    """rhythm_head.py (torch, scipy, wfdb) from this directory, also under `python -I`."""
    here = str(pathlib.Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import rhythm_head

    return rhythm_head


def _features_table(windows: np.ndarray) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    """Every statistic per window (NaN where refused) and the refusal counts by reason."""
    table = {k: np.full(len(windows), np.nan) for k in FEATURES}
    reasons: dict[str, int] = {}
    for i, w in enumerate(windows):
        got = window_features(w)
        if isinstance(got, str):
            reasons[got] = reasons.get(got, 0) + 1
            continue
        for k in FEATURES:
            table[k][i] = got[k]
    return table, reasons


def _mitdb_signal(root: pathlib.Path, name: str) -> tuple[np.ndarray, np.ndarray, int]:
    """MLII by name (the first lead of a few records is V5), at 250 Hz, plus beat annotations."""
    import wfdb

    rh = _rhythm_head()
    rec = wfdb.rdrecord(str(root / name))
    lead = rec.sig_name.index("MLII")
    x = rh.resample(rec.p_signal[:, lead].astype(np.float32), int(rec.fs))
    ann = wfdb.rdann(str(root / name), "atr")
    keep = np.array([s in BEAT_SYMBOLS for s in ann.symbol], dtype=bool)
    beats = np.asarray(ann.sample)[keep] * (FS / int(rec.fs))
    return x, beats, int(rec.fs)


def cmd_check_detector(args: argparse.Namespace) -> None:
    """Detector sensitivity and PPV (150 ms) on MIT-BIH Arrhythmia DS1, in independent 10 s windows."""
    root = pathlib.Path(args.data) / "mitdb" / "extracted"
    tot = np.zeros(3, dtype=int)
    per: dict[str, dict[str, float]] = {}
    for name in DS1:
        x, beats, _ = _mitdb_signal(root, name)
        det: list[int] = []
        for s0 in range(0, len(x) - WINDOW + 1, WINDOW):
            det += (detect_r_peaks(x[s0 : s0 + WINDOW]) + s0).tolist()
        covered = (len(x) // WINDOW) * WINDOW
        ref = beats[beats < covered]
        tp, fp, fn = match_beats(np.sort(ref), np.sort(np.asarray(det)), MATCH_TOL_S * FS)
        tot += (tp, fp, fn)
        per[name] = {"sensitivity": tp / max(tp + fn, 1), "ppv": tp / max(tp + fp, 1), "beats": float(len(ref))}
    res = {
        "records": len(DS1),
        "tp_fp_fn": tot.tolist(),
        "sensitivity": float(tot[0] / (tot[0] + tot[2])),
        "ppv": float(tot[0] / (tot[0] + tot[1])),
        "per_record": per,
        "match_tolerance_s": MATCH_TOL_S,
    }
    print(json.dumps({k: v for k, v in res.items() if k != "per_record"}, indent=1))
    worst = sorted(per.items(), key=lambda kv: kv[1]["sensitivity"] + kv[1]["ppv"])[:5]
    print("lowest five (sens, ppv):", [(n, round(v["sensitivity"], 3), round(v["ppv"], 3)) for n, v in worst])
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(res, indent=1))


def cmd_select(args: argparse.Namespace) -> None:
    """Choose the feature and threshold on CinC 2017 validation windows only; write the pin."""
    val = np.load(pathlib.Path(args.out) / "cinc_val.npz")
    y = val["y"]
    table, reasons = _features_table(val["X"])
    accepted = ~np.isnan(table[FEATURES[0]])
    af = (y == 1) & accepted
    rest = ((y == 0) | (y == 2)) & accepted
    use = af | rest
    aucs = {k: auroc(af[use], table[k][use]) for k in FEATURES}
    best = max(FEATURES, key=lambda k: aucs[k])
    t = threshold_for_specificity(af[use], table[best][use])
    got = rates(af[use], table[best][use] >= t)
    versus = {}
    for label, other in (("n", y == 0), ("other", y == 2)):
        m = (af | (other & accepted))
        versus[label] = auroc(af[m], table[best][m])
    sel = {
        "feature": best,
        "threshold": t,
        "rule": f"smallest threshold with specificity >= {MIN_SPECIFICITY} on accepted CinC 2017 validation windows",
        "validation": {
            "windows": int(len(y)),
            "accepted": int(accepted.sum()),
            "refused_by_reason": reasons,
            "af_windows": int(af.sum()),
            "non_af_windows": int(rest.sum()),
            "auroc_by_feature": aucs,
            "auroc_selected_af_vs_n": versus["n"],
            "auroc_selected_af_vs_other": versus["other"],
            "sensitivity": got["sensitivity"],
            "specificity": got["specificity"],
        },
        "detector": {
            "fs": FS,
            "window": WINDOW,
            "min_beats": MIN_BEATS,
            "median_rr_s": [MIN_MEDIAN_RR_S, MAX_MEDIAN_RR_S],
            "refractory_s": REFRACTORY_S,
            "threshold_fraction": THRESHOLD_FRACTION,
        },
    }
    text = json.dumps(sel, indent=1) + "\n"
    pathlib.Path(args.sel).write_text(text)
    print(text)


def _afdb_windows(root: pathlib.Path) -> Iterator[tuple[str, np.ndarray, np.ndarray]]:
    """(record, raw 250 Hz windows, label 0 N / 1 AF / 2 other) on exactly the head's AFDB windows:
    non-overlapping 10 s, at least 90% of one rhythm label, no missing sample."""
    import wfdb

    rh = _rhythm_head()

    for name in sorted({p.stem for p in root.rglob("*.hea")}):
        try:
            x, fs, _ = rh.load_wfdb(root, name, 0)
        except Exception:  # two of the 25 records have no signal file
            continue
        x = rh.resample(x, fs)
        ann = wfdb.rdann(str(root / name), "atr")
        lab = np.full(len(x), -1, np.int8)
        known = {"(AFIB": 1, "(AFL": 1, "(N": 0, "(J": 2}
        idx = (np.array(ann.sample) * (FS / fs)).astype(int)
        for i, note in enumerate([(s or "").strip("\x00") for s in ann.aux_note]):
            if note in known:
                end = idx[i + 1] if i + 1 < len(idx) else len(x)
                lab[idx[i] : end] = known[note]
        wins, ys = [], []
        for s0 in range(0, len(x) - WINDOW + 1, WINDOW):
            seg = lab[s0 : s0 + WINDOW]
            if (seg < 0).any() or np.isnan(x[s0 : s0 + WINDOW]).any():
                continue
            vals, cnt = np.unique(seg, return_counts=True)
            if cnt.max() / WINDOW < 0.9:
                continue
            wins.append(x[s0 : s0 + WINDOW])
            ys.append(int(vals[cnt.argmax()]))
        if wins:
            yield name, np.stack(wins), np.array(ys)


def _head_probabilities(raw: np.ndarray, session: Any) -> np.ndarray:
    """The deployed preprocessing (causal band-pass from zero state, median/MAD) then the FP32 head."""
    import scipy.signal as sps

    rh = _rhythm_head()

    x = rh.robust_norm(np.stack([sps.sosfilt(rh._SOS, w).astype(np.float32) for w in raw]))
    out = [session.run(None, {"ecg": x[i : i + 512, None, None, :]})[0] for i in range(0, len(x), 512)]
    z = np.concatenate(out)
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def cmd_score(args: argparse.Namespace) -> None:
    """Score AFDB once with the pinned feature and threshold, head and baseline on the same windows."""
    import onnxruntime as ort

    sel = json.loads(pathlib.Path(args.sel).read_text())
    head_threshold = float(np.load(args.weights)["af_threshold"][0])
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    session = ort.InferenceSession(
        str(pathlib.Path(args.out) / "tiny_fp32.onnx"), opts, providers=["CPUExecutionProvider"]
    )
    records: list[Record] = []
    reasons: dict[str, int] = {}
    names: list[str] = []
    for name, raw, y in _afdb_windows(pathlib.Path(args.data) / "afdb" / "extracted"):
        table, why = _features_table(raw)
        for k, v in why.items():
            reasons[k] = reasons.get(k, 0) + v
        records.append(Record(y, _head_probabilities(raw, session), table[sel["feature"]]))
        names.append(name)

    def statistics(recs: Sequence[Record]) -> dict[str, float]:
        return baseline_stats(recs, head_threshold, float(sel["threshold"]))

    res = {
        "windows": int(sum(len(r.y) for r in records)),
        "records": len(records),
        "feature": sel["feature"],
        "base_threshold": sel["threshold"],
        "head_threshold": head_threshold,
        "base_refused_by_reason": reasons,
        "af_prevalence": float(np.mean(np.concatenate([r.y for r in records]) == 1)),
        "bootstrap": {"resamples": N_BOOT, "seed": SEED, "unit": "record"},
        "metrics": record_bootstrap(records, statistics),
        "per_record_names": names,
    }
    out = pathlib.Path(args.out) / "rr_baseline_afdb.json"
    out.write_text(json.dumps(res, indent=1))
    for key, v in res["metrics"].items():
        print(f"{key:24s} {v['point']:.4f}  [{v['lo']:.4f}, {v['hi']:.4f}]")
    print({k: v for k, v in res.items() if k not in ("metrics", "per_record_names")})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    here = pathlib.Path(__file__).resolve().parent
    default_sel = here / "rr_baseline_selection.json"
    default_weights = here.parent / "models" / "tier_b" / "arrhythmia" / "weights.npz"
    p = sub.add_parser("check-detector")
    p.add_argument("--data", required=True)
    p.add_argument("--json")
    p.set_defaults(fn=cmd_check_detector)
    p = sub.add_parser("select")
    p.add_argument("--out", required=True, help="rhythm_head.py output dir holding cinc_val.npz")
    p.add_argument("--sel", default=str(default_sel))
    p.set_defaults(fn=cmd_select)
    p = sub.add_parser("score")
    p.add_argument("--data", required=True)
    p.add_argument("--out", required=True, help="rhythm_head.py output dir holding tiny_fp32.onnx")
    p.add_argument("--sel", default=str(default_sel))
    p.add_argument("--weights", default=str(default_weights))
    p.set_defaults(fn=cmd_score)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
