# training/

Offline model training for BioSentry. **Not part of the application**: nothing here is imported by
`backend/` or `frontend/`, and no data is committed (README I5; PhysioNet licences). The trained
weights and parity vectors of the rhythm head live under `models/tier_b/arrhythmia/` behind a
registry sha256; they contain no recordings. The isolation is enforced, not just stated:
`backend/tests/unit/test_training_isolation.py` fails the build if anything here imports
`biosentry.*` or references `data/synthetic` (I5).

Status: **spike (M3b)**, retrospective and on public data only.

## What is here

| File | Purpose |
|------|---------|
| `rhythm_head.py` | Tiny 1-D CNN rhythm head (N / AF / Other / Noisy) on 10 s single-lead ECG windows: `inspect`, `prep`, `train`, `eval`, `opt`, `export` |
| `fetch_data.py` | Downloads the open PhysioNet corpora, verifies SHA-256 sums by exact path |
| `export_numpy.py` | Turns the FP32 and INT8 ONNX files into `weights.npz` and `golden.npz` for the backend's numpy forward pass (needs `rhythm_head.py` beside it, so no `-I`) |
| `golden_windows.py` | The seeded synthetic windows behind `golden.npz` (numpy only; a test regenerates them from the seed) |
| `rr_baseline.py` | Classical RR-irregularity AF baseline for the M3 exit gate: `check-detector` (MIT-BIH DS1 only), `select` (feature and threshold from CinC validation only), `score` (AFDB, head and baseline on the same windows, paired record-level bootstrap). Numpy only at import; its pure functions are tested in `backend/tests/unit/test_rr_baseline.py` |
| `rr_baseline_selection.json` | The pinned choice `select` wrote before AFDB was scored, with the detector's constants |
| `bench_ort.py` | CPU latency (p50, p95 per window and per patient-minute) and peak RSS of the FP32 or INT8 network under ONNX Runtime, batch 1, one thread |
| `pyproject.toml` | Own project, exact pins, Python 3.11 |
| `constraints.txt` | Exact versions of the whole dependency closure (use with `pip install -c`) |

## Run

```bash
cd training
python3.11 -m venv .venv && .venv/bin/pip install -c constraints.txt -e .
.venv/bin/python -I fetch_data.py --data data            # ~850 MB; --dry-run lists first
.venv/bin/python -I rhythm_head.py prep   --data data --out out
.venv/bin/python -I rhythm_head.py train  --data data --out out --epochs 12
.venv/bin/python -I rhythm_head.py eval   --data data --out out
.venv/bin/python -I rhythm_head.py opt    --data data --out out    # operating point from validation only
.venv/bin/python -I rhythm_head.py export --data data --out out    # ONNX FP32 + INT8, latency
.venv/bin/python export_numpy.py --onnx-dir out --models-dir ../models/tier_b/arrhythmia

# the classical baseline and the timing (M3 exit gate); run the selection BEFORE the scoring
.venv/bin/python -I rr_baseline.py check-detector --data data
.venv/bin/python -I rr_baseline.py select --out out
.venv/bin/python -I rr_baseline.py score  --data data --out out
.venv/bin/python -I bench_ort.py --onnx out/tiny_fp32.onnx
```

Run with `-I` and keep downloaded data in its own directory: treat it as untrusted input.

## Data (open access, Open Data Commons Attribution 1.0)

| Corpus | Use | Approx. size |
|--------|-----|--------------|
| PhysioNet/CinC Challenge 2017 training set (doi 10.13026/d3hm-sf11) | train / validation / test, split by record | 99 MB zip |
| MIT-BIH Noise Stress Test DB, bw/em/ma noise records (10.13026/C2HS3T) | noise augmentation (first half), robustness test (second half) | 6 MB |
| MIT-BIH Atrial Fibrillation DB (10.13026/C2MW2D) | external test only, never trained on | 635 MB |
| MIT-BIH Arrhythmia DB (10.13026/C2F305) | R-peak detector check of the RR baseline on DS1 only (paced records and 202 out); DS2 untouched, reserved for the PVC metric | 109 MB |

## Spike results (retrospective, public data; see Limits)

Model: 88,972 parameters; FP32 ONNX 350 KB, INT8 110 KB; per 10 s window 0.23 ms (FP32) / 0.07 ms (INT8), p95
within 0.003 ms (1 thread, batch 1, Apple M4, ONNX Runtime; the model card has the full table). The AFDB and CinC
lines below are the stream-filtered training protocol; the deployed per-window numbers and the comparison with a
classical RR rule are in the model card.

- External AFDB (23 records, 83,863 windows): AF AUROC 0.966; at the threshold chosen on CinC validation only
  (0.20) sensitivity 0.84, specificity 0.97, per-record burden MAE 0.077 (Pearson r 0.94).
- CinC test-split records: macro-F1 0.68 (N 0.85, AF 0.77, Other 0.65, Noisy 0.46), AF AUROC 0.965.
- INT8 vs FP32: macro-F1 0.6814 vs 0.6814, AF AUROC 0.9655 vs 0.9656, 98.8% identical predictions.
- Noise: AF AUROC >= 0.96 down to 12 dB SNR; 0.93-0.94 at 6 dB; at 0 dB 89-98% of windows are flagged Noisy.

## Limits

- Not chest-patch, ward or Philippine data; the sources are a handheld recorder (CinC) and Holter (AFDB).
- CinC is split by record because patient IDs are not available: possible optimistic leakage.
- AFDB windows need >= 90% of one rhythm label, so transitional windows are excluded.
- NSTDB train and test halves come from the same three noise records.
- Single lead; no PVC head, no beat localisation.
- Claims language: "retrospective, public data". Not validated, not a diagnosis; it displays and a human decides (it does not rank: I3).

## Rules this code follows

- I1 missing is missing: windows containing NaN are dropped, never filled.
- I5 no training on BioSentry patients: public corpora only; local data would only calibrate and validate.
- Burden = AF windows / accepted windows; Noisy windows leave the denominator, they never count as normal.
