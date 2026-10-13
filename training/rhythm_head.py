#!/usr/bin/env python
"""M3b spike: tiny CNN rhythm head (N / AF / Other / Noisy) on open PhysioNet data.

Run isolated: python -I rhythm_head.py <cmd> --data DATA_DIR --out OUT_DIR
Data comes from fetch_data.py (nothing is committed). See README.md.
Commands: inspect | prep | train | eval | export

Rules honoured (README I1/I5): public open-access corpora only, no imputation
(windows containing NaN are dropped, never filled), no BioSentry patient data.
"""
import argparse, json, os, pathlib, sys, time
import numpy as np
from scipy import signal as sps
from scipy.io import loadmat

FS = 250                 # model sampling rate (Hz)
WIN_S = 10
WIN = FS * WIN_S         # 2500 samples
STRIDE_S = 5
CLASSES = ["N", "AF", "Other", "Noisy"]
SEED = 20261013


# ------------------------------------------------------------------ io / dsp
def resample(x, fs_in, fs_out=FS):
    if fs_in == fs_out:
        return x.astype(np.float32)
    from math import gcd
    g = gcd(int(fs_in), int(fs_out))
    return sps.resample_poly(x, fs_out // g, fs_in // g).astype(np.float32)


_SOS = sps.butter(2, [0.5, 40.0], btype="bandpass", fs=FS, output="sos")


def bandpass(x):
    """Causal 0.5-40 Hz band-pass (deployable on a stream; no look-ahead)."""
    return sps.sosfilt(_SOS, x).astype(np.float32)


def robust_norm(w):
    med = np.median(w, axis=-1, keepdims=True)
    mad = np.median(np.abs(w - med), axis=-1, keepdims=True) * 1.4826
    return np.clip((w - med) / (mad + 1e-6), -10.0, 10.0).astype(np.float32)


def windows(x, stride_s=STRIDE_S):
    """Non-NaN 10 s windows; returns array (n, WIN) and start indices."""
    step = stride_s * FS
    starts = np.arange(0, len(x) - WIN + 1, step)
    if len(starts) == 0:
        return np.zeros((0, WIN), np.float32), starts
    idx = starts[:, None] + np.arange(WIN)[None, :]
    w = x[idx]
    ok = ~np.isnan(w).any(axis=1)          # I1: never fill, drop
    return w[ok], starts[ok]


# --------------------------------------------------------------- datasets
def load_cinc(root):
    root = pathlib.Path(root)
    ref = None
    for cand in ["REFERENCE-v3.csv", "REFERENCE.csv"]:
        for p in root.rglob(cand):
            ref = p
            break
        if ref:
            break
    assert ref is not None, "REFERENCE csv not found"
    lab = {}
    for line in ref.read_text().strip().splitlines():
        name, c = line.split(",")[:2]
        lab[name.strip()] = c.strip()
    cmap = {"N": 0, "A": 1, "O": 2, "~": 3}
    recs = []
    for name, c in sorted(lab.items()):
        m = next(root.rglob(f"{name}.mat"), None)
        if m is None:
            continue
        x = loadmat(m)["val"][0].astype(np.float32) / 1000.0   # mV
        recs.append((name, cmap[c], x))
    return recs


def load_wfdb(root, name, ch=0):
    import wfdb
    r = wfdb.rdrecord(str(pathlib.Path(root) / name))
    return r.p_signal[:, ch].astype(np.float32), int(r.fs), r


def build_cinc_windows(recs):
    X, y, g = [], [], []
    for gi, (name, c, x) in enumerate(recs):
        x = bandpass(resample(x, 300))
        w, _ = windows(x)
        if len(w) == 0:
            continue
        X.append(w); y += [c] * len(w); g += [gi] * len(w)
    return np.concatenate(X), np.array(y, np.int64), np.array(g, np.int64)


def split_records(recs, seed=SEED):
    """Stratified 80/10/10 split by record (patients are not identifiable)."""
    rng = np.random.default_rng(seed)
    by = {}
    for i, (_, c, _) in enumerate(recs):
        by.setdefault(c, []).append(i)
    tr, va, te = [], [], []
    for c, ids in by.items():
        ids = np.array(ids); rng.shuffle(ids)
        n = len(ids); a, b = int(0.8 * n), int(0.9 * n)
        tr += ids[:a].tolist(); va += ids[a:b].tolist(); te += ids[b:].tolist()
    return sorted(tr), sorted(va), sorted(te)


# ------------------------------------------------------------------ model
def make_model():
    import torch.nn as nn
    import torch

    def blk(cin, cout, k, stride=1, dil=1):
        pad = (k // 2) * dil
        return [nn.Conv2d(cin, cout, (1, k), stride=(1, stride), padding=(0, pad),
                          dilation=(1, dil), bias=False),
                nn.BatchNorm2d(cout), nn.ReLU(inplace=True)]

    class Tiny(nn.Module):
        """1-D CNN written with 2-D ops (1 x k kernels) so MindSpore Lite's
        ONNX converter sees plain Conv/BN/ReLU/GlobalPool/Gemm."""
        def __init__(self, n_classes=4):
            super().__init__()
            L = []
            L += blk(1, 8, 7, 2) + blk(8, 16, 5, 2) + blk(16, 32, 5, 2)
            L += blk(32, 48, 5, 2) + blk(48, 64, 5, 2)
            L += blk(64, 64, 5, 1, 2) + blk(64, 64, 5, 1, 4) + blk(64, 64, 5, 1, 8)
            self.features = nn.Sequential(*L)
            self.avg = nn.AdaptiveAvgPool2d(1)
            self.max = nn.AdaptiveMaxPool2d(1)
            self.fc = nn.Linear(128, n_classes)

        def forward(self, x):                      # x: (N, 1, 1, WIN)
            h = self.features(x)
            h = torch.cat([self.avg(h).flatten(1), self.max(h).flatten(1)], 1)
            return self.fc(h)

    return Tiny()


# --------------------------------------------------------------- noise bank
def noise_bank(nst_root):
    """NSTDB noise records bw/em/ma, resampled; first half = train, second = test."""
    bank = {}
    for n in ["bw", "em", "ma"]:
        x, fs, _ = load_wfdb(nst_root, n, 0)
        x = bandpass(resample(x, fs))
        h = len(x) // 2
        bank[n] = (x[:h], x[h:])
    return bank


def add_noise(clean, noise, snr_db, rng):
    """clean: (WIN,) filtered mV; noise: long vector; returns clean + scaled noise."""
    i = rng.integers(0, len(noise) - WIN)
    nz = noise[i:i + WIN]
    pc = np.sqrt(np.mean(clean ** 2)) + 1e-9
    pn = np.sqrt(np.mean(nz ** 2)) + 1e-9
    a = pc / (pn * 10 ** (snr_db / 20.0))
    return (clean + a * nz).astype(np.float32)


# ------------------------------------------------------------------ metrics
def f1_from_cm(cm):
    out = []
    for k in range(cm.shape[0]):
        tp = cm[k, k]; fp = cm[:, k].sum() - tp; fn = cm[k, :].sum() - tp
        out.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return out


def auroc(y, s):
    from sklearn.metrics import roc_auc_score
    y = np.asarray(y); s = np.asarray(s)
    return float(roc_auc_score(y, s)) if 0 < y.sum() < len(y) else float("nan")


def ece(p, y, bins=10):
    p = np.asarray(p); y = np.asarray(y)
    e = 0.0
    for lo in np.linspace(0, 1, bins, endpoint=False):
        m = (p >= lo) & (p < lo + 1.0 / bins)
        if m.any():
            e += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(e)


# ------------------------------------------------------------------- commands
def cmd_inspect(a):
    root = pathlib.Path(a.data)
    for d in ["cinc2017", "mitdb", "afdb", "nstdb"]:
        files = [p for p in (root / d / "extracted").rglob("*") if p.is_file()]
        exts = {}
        for p in files:
            exts[p.suffix] = exts.get(p.suffix, 0) + 1
        print(d, len(files), "files", dict(sorted(exts.items())))
    recs = load_cinc(root / "cinc2017" / "extracted")
    from collections import Counter
    print("cinc records", len(recs), Counter(c for _, c, _ in recs))
    lens = np.array([len(x) / 300 for _, _, x in recs])
    print("cinc length s: min %.1f median %.1f max %.1f; <10 s: %d" %
          (lens.min(), np.median(lens), lens.max(), (lens < 10).sum()))


def cmd_prep(a):
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    recs = load_cinc(pathlib.Path(a.data) / "cinc2017" / "extracted")
    tr, va, te = split_records(recs)
    json.dump({"train": tr, "val": va, "test": te}, open(out / "split.json", "w"))
    for tag, ids in [("train", tr), ("val", va), ("test", te)]:
        X, y, g = build_cinc_windows([recs[i] for i in ids])
        np.savez_compressed(out / f"cinc_{tag}.npz", X=X, y=y, g=g)
        print(tag, X.shape, np.bincount(y, minlength=4).tolist())


def cmd_train(a):
    import torch, torch.nn as nn
    torch.manual_seed(SEED); np.random.seed(SEED)
    out = pathlib.Path(a.out)
    tr = np.load(out / "cinc_train.npz"); va = np.load(out / "cinc_val.npz")
    bank = noise_bank(pathlib.Path(a.data) / "nstdb" / "extracted")
    Xtr, ytr = tr["X"], tr["y"]
    rng = np.random.default_rng(SEED)
    cls_w = torch.tensor(1.0 / np.maximum(np.bincount(ytr, minlength=4), 1), dtype=torch.float32)
    cls_w = cls_w / cls_w.sum() * 4
    model = make_model()
    n_par = sum(p.numel() for p in model.parameters())
    print("params", n_par)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-3)
    E, B = a.epochs, 256
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=E * ((len(Xtr) + B - 1) // B))
    lossf = nn.CrossEntropyLoss(weight=cls_w)
    nz_names = list(bank)

    def batch(idx):
        xs, ys = [], []
        for i in idx:
            x, y = Xtr[i], int(ytr[i])
            r = rng.random()
            nb = bank[nz_names[rng.integers(0, 3)]][0]     # train half only
            if r < 0.35 and y != 3:                         # moderate noise, label kept
                x = add_noise(x, nb, rng.uniform(6, 24), rng)
            elif r < 0.45 and y != 3:                       # very noisy -> Noisy class
                x = add_noise(x, nb, rng.uniform(-6, 0), rng); y = 3
            xs.append(robust_norm(x)); ys.append(y)
        return (torch.from_numpy(np.stack(xs))[:, None, None, :],
                torch.tensor(ys))

    Xv, yv = va["X"], va["y"]
    Xvn = torch.from_numpy(robust_norm(Xv))[:, None, None, :]
    best, t0 = 0.0, time.time()
    for ep in range(E):
        model.train()
        perm = rng.permutation(len(Xtr))
        tot = 0.0
        for s in range(0, len(perm), B):
            xb, yb = batch(perm[s:s + B])
            opt.zero_grad(); loss = lossf(model(xb), yb); loss.backward(); opt.step(); sched.step()
            tot += float(loss) * len(yb)
        model.eval()
        with torch.no_grad():
            pv = torch.cat([model(Xvn[i:i + 1024]) for i in range(0, len(Xvn), 1024)]).argmax(1).numpy()
        cm = np.zeros((4, 4), int)
        for t, p in zip(yv, pv):
            cm[t, p] += 1
        f1 = f1_from_cm(cm); mf1 = float(np.mean(f1))
        print(f"ep {ep+1}/{E} loss {tot/len(perm):.4f} val macro-F1 {mf1:.3f} per-class {np.round(f1,3).tolist()} {time.time()-t0:.0f}s", flush=True)
        if mf1 > best:
            best = mf1; torch.save(model.state_dict(), out / "tiny_fp32.pt")
    json.dump({"params": n_par, "best_val_macro_f1": best, "epochs": E}, open(out / "train.json", "w"))


def load_model(out):
    import torch
    m = make_model(); m.load_state_dict(torch.load(pathlib.Path(out) / "tiny_fp32.pt")); m.eval()
    return m


def predict(model, X, bs=1024):
    import torch
    outs = []
    with torch.no_grad():
        for i in range(0, len(X), bs):
            xb = torch.from_numpy(robust_norm(X[i:i + bs]))[:, None, None, :]
            outs.append(torch.softmax(model(xb), 1).numpy())
    return np.concatenate(outs) if outs else np.zeros((0, 4), np.float32)


def afdb_windows(root, ch=0, stride_s=WIN_S):
    """Yield (record, X windows, y) with rhythm label by >=90% coverage."""
    import wfdb
    names = sorted({p.stem for p in pathlib.Path(root).rglob("*.hea")})
    for n in names:
        try:
            x, fs, r = load_wfdb(root, n, ch)
        except Exception:
            continue
        x = bandpass(resample(x, fs))
        ann = wfdb.rdann(str(pathlib.Path(root) / n), "atr")
        lab = np.full(len(x), -1, np.int8)
        rm = {"(AFIB": 1, "(AFL": 1, "(N": 0, "(J": 2}
        idx = (np.array(ann.sample) * (FS / fs)).astype(int)
        names_ = [(s or "") for s in ann.aux_note]
        for i, s in enumerate(names_):
            s = s.strip("\x00")
            if s in rm:
                end = idx[i + 1] if i + 1 < len(idx) else len(x)
                lab[idx[i]:end] = rm[s]
        step = stride_s * FS
        starts = np.arange(0, len(x) - WIN + 1, step)
        X, y = [], []
        for s0 in starts:
            seg = lab[s0:s0 + WIN]
            if (seg < 0).any():
                continue
            vals, cnt = np.unique(seg, return_counts=True)
            if cnt.max() / WIN < 0.9:
                continue
            w = x[s0:s0 + WIN]
            if np.isnan(w).any():
                continue
            X.append(w); y.append(int(vals[cnt.argmax()]))
        if X:
            yield n, np.stack(X), np.array(y)


def cmd_eval(a):
    out = pathlib.Path(a.out)
    model = load_model(out)
    res = {}
    te = np.load(out / "cinc_test.npz"); va = np.load(out / "cinc_val.npz")
    # temperature scaling on val (calibration of the AF probability)
    import torch
    pv = predict(model, va["X"]); logit = np.log(np.clip(pv, 1e-7, 1))
    best_T, best_nll = 1.0, 9e9
    for T in np.linspace(0.5, 3.0, 26):
        z = logit / T; z -= z.max(1, keepdims=True)
        p = np.exp(z); p /= p.sum(1, keepdims=True)
        nll = -np.log(p[np.arange(len(va["y"])), va["y"]] + 1e-9).mean()
        if nll < best_nll:
            best_nll, best_T = nll, float(T)
    res["temperature"] = best_T
    pt = predict(model, te["X"]); yt = te["y"]
    cm = np.zeros((4, 4), int)
    for t, p in zip(yt, pt.argmax(1)):
        cm[t, p] += 1
    res["cinc_test"] = {"n_windows": int(len(yt)), "confusion": cm.tolist(),
                        "f1_per_class": dict(zip(CLASSES, np.round(f1_from_cm(cm), 4).tolist())),
                        "macro_f1": float(np.mean(f1_from_cm(cm))),
                        "af_auroc": auroc(yt == 1, pt[:, 1]),
                        "af_ece": ece(pt[:, 1], (yt == 1).astype(float))}
    # external: MIT-BIH AFDB (different device, 250 Hz, never trained on)
    ys, ps, per_rec = [], [], {}
    for n, X, y in afdb_windows(pathlib.Path(a.data) / "afdb" / "extracted"):
        p = predict(model, X)
        ys.append(y); ps.append(p)
        acc = p.argmax(1)
        valid = acc != 3
        est = float((acc[valid] == 1).mean()) if valid.any() else float("nan")
        per_rec[n] = {"windows": int(len(y)), "true_burden": float((y == 1).mean()),
                      "est_burden": est, "rejected": float((~valid).mean())}
    y = np.concatenate(ys); p = np.concatenate(ps)
    af = (y == 1)
    pred = p.argmax(1)
    acc_mask = pred != 3
    res["afdb_external"] = {
        "n_windows": int(len(y)), "af_prevalence": float(af.mean()),
        "af_auroc": auroc(af, p[:, 1]),
        "af_f1_argmax": float(2 * ((pred == 1) & af).sum() / max(((pred == 1).sum() + af.sum()), 1)),
        "af_sensitivity": float(((pred == 1) & af).sum() / max(af.sum(), 1)),
        "af_specificity": float(((pred != 1) & ~af).sum() / max((~af).sum(), 1)),
        "rejected_as_noisy": float((~acc_mask).mean()),
        "burden_mae": float(np.nanmean([abs(v["est_burden"] - v["true_burden"]) for v in per_rec.values()])),
        "per_record": per_rec}
    # noise robustness: AFDB subsample + NSTDB TEST half noise
    bank = noise_bank(pathlib.Path(a.data) / "nstdb" / "extracted")
    rng = np.random.default_rng(SEED)
    Xs, ys2 = [], []
    for n, X, yy in afdb_windows(pathlib.Path(a.data) / "afdb" / "extracted", stride_s=60):
        Xs.append(X); ys2.append(yy)
    Xs = np.concatenate(Xs); ys2 = np.concatenate(ys2)
    rob = {}
    for kind in ["em", "ma", "bw"]:
        for snr in [24, 18, 12, 6, 0, -6]:
            Xn = np.stack([add_noise(x, bank[kind][1], snr, rng) for x in Xs])
            pn = predict(model, Xn)
            rob[f"{kind}@{snr}dB"] = {"af_auroc": auroc(ys2 == 1, pn[:, 1]),
                                      "noisy_rate": float((pn.argmax(1) == 3).mean())}
    res["noise_robustness_afdb_nstdb_test_half"] = {"n_windows": int(len(Xs)), **rob}
    json.dump(res, open(out / "eval.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "noise_robustness_afdb_nstdb_test_half"}, indent=1)[:3000])
    for k, v in rob.items():
        print(k, round(v["af_auroc"], 3), "noisy", round(v["noisy_rate"], 2))


def cmd_opt(a):
    """Pick the AF operating point on CinC *validation* only, then apply it to AFDB (external)."""
    out = pathlib.Path(a.out)
    model = load_model(out)
    va = np.load(out / "cinc_val.npz")
    pv = predict(model, va["X"]); yv = va["y"]
    keep = pv.argmax(1) != 3                      # windows the model accepts
    af = (yv == 1) & keep; rest = ((yv == 0) | (yv == 2)) & keep
    best = None
    for t in np.linspace(0.05, 0.95, 91):
        sens = float(((pv[:, 1] >= t) & af).sum() / max(af.sum(), 1))
        spec = float(((pv[:, 1] < t) & rest).sum() / max(rest.sum(), 1))
        if spec >= 0.95 and (best is None or sens > best[1]):
            best = (float(t), sens, spec)
    t = best[0]
    res = {"threshold": t, "val_sens": best[1], "val_spec": best[2]}
    ys, ps, per = [], [], {}
    for n, X, y in afdb_windows(pathlib.Path(a.data) / "afdb" / "extracted"):
        p = predict(model, X); acc = p.argmax(1) != 3
        est = float((p[acc, 1] >= t).mean()) if acc.any() else float("nan")
        per[n] = (float((y == 1).mean()), est)
        ys.append(y[acc]); ps.append(p[acc])
    y = np.concatenate(ys); p = np.concatenate(ps); af = y == 1
    res["afdb_sens"] = float(((p[:, 1] >= t) & af).sum() / af.sum())
    res["afdb_spec"] = float(((p[:, 1] < t) & ~af).sum() / (~af).sum())
    errs = [abs(e - tb) for tb, e in per.values()]
    res["afdb_burden_mae"] = float(np.nanmean(errs))
    res["afdb_burden_pearson"] = float(np.corrcoef([v[0] for v in per.values()], [v[1] for v in per.values()])[0, 1])
    json.dump(res, open(out / "operating_point.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


def cmd_export(a):
    import torch, onnx, onnxruntime as ort
    out = pathlib.Path(a.out)
    model = load_model(out)
    dummy = torch.zeros(1, 1, 1, WIN)
    path = out / "tiny_fp32.onnx"
    torch.onnx.export(model, dummy, str(path), input_names=["ecg"], output_names=["logits"],
                      dynamic_axes={"ecg": {0: "n"}, "logits": {0: "n"}}, opset_version=17, dynamo=False)
    onnx.checker.check_model(onnx.load(str(path)))
    te = np.load(out / "cinc_test.npz")
    Xn = robust_norm(te["X"][:512])[:, None, None, :].astype(np.float32)
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    with torch.no_grad():
        ref = model(torch.from_numpy(Xn)).numpy()
    got = sess.run(None, {"ecg": Xn})[0]
    rep = {"onnx_bytes": path.stat().st_size, "torch_vs_ort_max_abs_diff": float(np.abs(ref - got).max())}

    def lat(sess, threads):
        so = ort.SessionOptions(); so.intra_op_num_threads = threads
        s = ort.InferenceSession(sess, so, providers=["CPUExecutionProvider"])
        x = Xn[:1]
        for _ in range(20):
            s.run(None, {"ecg": x})
        t = []
        for _ in range(300):
            t0 = time.perf_counter(); s.run(None, {"ecg": x}); t.append((time.perf_counter() - t0) * 1e3)
        return float(np.median(t)), float(np.percentile(t, 95))
    rep["fp32_ms_per_10s_1thread_median_p95"] = lat(str(path), 1)
    # INT8 static quantisation (QDQ, per-channel)
    from onnxruntime.quantization import quantize_static, CalibrationDataReader, QuantFormat, QuantType

    class Reader(CalibrationDataReader):
        def __init__(self):
            self.it = iter([{"ecg": Xn[i:i + 1]} for i in range(0, 256, 2)])
        def get_next(self):
            return next(self.it, None)
    q = out / "tiny_int8.onnx"
    quantize_static(str(path), str(q), Reader(), quant_format=QuantFormat.QDQ,
                    per_channel=True, weight_type=QuantType.QInt8, activation_type=QuantType.QInt8)
    rep["int8_bytes"] = q.stat().st_size
    rep["int8_ms_per_10s_1thread_median_p95"] = lat(str(q), 1)
    sq = ort.InferenceSession(str(q), providers=["CPUExecutionProvider"])
    pf = predict_ort(sess, te["X"]); pq = predict_ort(sq, te["X"])
    yt = te["y"]
    def mf1(p):
        cm = np.zeros((4, 4), int)
        for t, pp in zip(yt, p.argmax(1)):
            cm[t, pp] += 1
        return float(np.mean(f1_from_cm(cm)))
    rep["cinc_test_macro_f1_fp32_ort"] = mf1(pf)
    rep["cinc_test_macro_f1_int8_ort"] = mf1(pq)
    rep["af_auroc_fp32_ort"] = auroc(yt == 1, pf[:, 1]); rep["af_auroc_int8_ort"] = auroc(yt == 1, pq[:, 1])
    rep["argmax_agreement_fp32_vs_int8"] = float((pf.argmax(1) == pq.argmax(1)).mean())
    json.dump(rep, open(out / "export.json", "w"), indent=1)
    print(json.dumps(rep, indent=1))


def predict_ort(sess, X, bs=512):
    outs = []
    for i in range(0, len(X), bs):
        xb = robust_norm(X[i:i + bs])[:, None, None, :].astype(np.float32)
        lg = sess.run(None, {"ecg": xb})[0]
        e = np.exp(lg - lg.max(1, keepdims=True)); outs.append(e / e.sum(1, keepdims=True))
    return np.concatenate(outs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["inspect", "prep", "train", "eval", "export", "opt"])
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=12)
    a = ap.parse_args()
    {"inspect": cmd_inspect, "prep": cmd_prep, "train": cmd_train, "eval": cmd_eval, "export": cmd_export, "opt": cmd_opt}[a.cmd](a)
