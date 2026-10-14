# Tier B arrhythmia head: tiny rhythm CNN (M3b spike)

| | |
|---|---|
| id | `tier_b/arrhythmia` |
| tier | B (mechanism finding) |
| version | 0.1.0-spike |
| status | **research**: trained for study; not for ranking, not for product use |
| artifact | `weights.npz` (FP32 and INT8 arrays, band-pass coefficients); sha256 pinned in `models/registry.yaml` |
| parity vectors | `golden.npz`: ten seeded synthetic windows, reference intermediates and ONNX Runtime logits |
| use | evaluation and development only, until the user clears the open licence note below |
| claims | retrospective, public data. Never "validated", "beats NEWS2" or "hours earlier" (P10) |

## What it does

Labels one 10 s window of single-lead ECG as one of four classes: `N` (normal rhythm), `AF`,
`Other` rhythm, `Noisy`. The Tier B finding is **AF burden** = windows labelled AF / windows
accepted (a `Noisy` window is a refusal and leaves the denominator; a gap is never counted as
normal or as AF), reported with its coverage. It displays; a human decides. It does not rank (Tier B
never ranks, I3) and it is not a diagnosis.

## Interface

- Input: 250 Hz, 2500 samples (10 s), contiguous and fully valid. A window with any unusable
  sample is not passed in and is refused (I1): nothing is filled, interpolated or resampled.
- Preprocessing (per window, so windows stay independent): causal Butterworth band-pass 0.5-40 Hz
  (order 2 per band edge, two second-order sections) with zero initial state, then median/MAD
  normalisation (MAD x 1.4826, +1e-6, clipped at +/-10). Measured against the stream-filtered
  distribution it was trained on, per-window filtering changed AFDB AF AUROC from 0.9655 to 0.9666
  and CinC macro-F1 from 0.681 to 0.683, so there was no retrain.
- Output: 4 logits (N, AF, Other, Noisy). AF operating point: p(AF) >= 0.20 among accepted
  windows, chosen on the CinC validation split only.
- Size: 88,612 weights after folding BatchNorm into the convolutions (88,972 parameters before);
  FP32 ONNX 350 KB, INT8 QDQ (static, per-channel) 110 KB. CPU, 1 thread, Apple M4, ONNX Runtime,
  median per 10 s window: FP32 0.45 ms, INT8 0.14 ms.
- Written as 1 x k Conv2d, ReLU, global average and max pooling, Gemm (converter-friendly for
  MindSpore Lite).

## Training data and licences (all public; no BioSentry patient data: I5)

Read on the PhysioNet project pages and their licence pages on 2026-10-14. Each project page
states "Open Data Commons Attribution License v1.0" and "Anyone can access the files, as long as
they conform to the terms of the specified license."; each licence page is ODC-By v1.0, whose
rights "explicitly include commercial use" (section 3.1) and whose only condition is the
attribution notice of section 4 (a publicly conveyed derivative database must stay under the same
licence; the weights contain no recordings). None states a non-commercial or no-redistribution
clause.

| Corpus | Use here | Version, DOI | Licence page |
|---|---|---|---|
| PhysioNet/CinC Challenge 2017 training set (8,528 single-lead 300 Hz recordings) | train, validation, test (split by record, stratified) | 1.0.0 (2017-02-01), https://doi.org/10.13026/d3hm-sf11 | https://physionet.org/content/challenge-2017/view-license/1.0.0/ |
| MIT-BIH Noise Stress Test Database | noise augmentation (first half of each noise record), robustness test (second half) | 1.0.0 (1999-08-03), https://doi.org/10.13026/C2HS3T | https://physionet.org/content/nstdb/view-license/1.0.0/ |
| MIT-BIH Atrial Fibrillation Database | external test only, never trained on | 1.0.0 (2000-11-04), https://doi.org/10.13026/C2MW2D | https://physionet.org/content/afdb/view-license/1.0.0/ |

Attribution (required): Clifford GD et al., "AF classification from a short single lead ECG
recording: the PhysioNet/Computing in Cardiology Challenge 2017", CinC 2017, DOI
10.22489/CinC.2017.065-469; Moody GB, Muldrow WE, Mark RG, "A noise stress test for arrhythmia
detectors", Computers in Cardiology 1984;11:381-384; Moody GB, Mark RG, "A new method for detecting
atrial fibrillation using R-R intervals", Computers in Cardiology 1983;10:227-230; and Pollard T
et al., "PhysioNet as a global platform for biomedical research", Nature Health 2026,
DOI 10.1038/s44360-026-00096-z.

**Open note (not decided here):** licence stated as ODC-By 1.0; the 2017 news post phrase is
unresolved; not cleared for product use. The CinC 2017 page's news post says the database "is
being made freely available exclusively for this competition by AliveCor"; the page states no
reuse restriction, and what that phrase means for weights trained on it has not been settled. The
Orchestrator ruled that ODC-By governs for shipping the weights with attribution at status
`research`, and is taking the phrase to the user as a clearance item. Until the user clears it,
the weights are for evaluation and development only.

The model was never trained, tuned or calibrated on BioSentry patients (I5). Local data, when it
exists, may only calibrate and validate.

## Results (retrospective, public data; external numbers are labelled external)

Deployed preprocessing (per window), FP32 unless stated. Windows are non-overlapping 10 s.

| Set | Result |
|---|---|
| CinC 2017 held-out records (internal; 4,683 windows) | macro-F1 0.683 (95% CI 0.630-0.726); F1 N 0.847, AF 0.765, Other 0.654, Noisy 0.465; AF AUROC 0.965 (0.938-0.985); AF ECE 0.019 |
| **AFDB, external** (83,863 windows, 23 records, never trained on) | AF AUROC 0.967 over all windows (0.944-0.984; 0.979 among accepted); at p(AF) >= 0.20, among accepted windows: sensitivity 0.846 (0.745-0.936), specificity 0.972 (0.940-0.991); 5.2% of windows refused as Noisy (3.3-7.5%); per-record burden MAE 0.076 (0.035-0.124), Pearson r 0.940; worst record 05121 |
| INT8 (ONNX Runtime) vs FP32 | AFDB sensitivity 0.851 (0.751-0.939), specificity 0.971 (0.937-0.990), burden MAE 0.075 (0.035-0.122); CinC macro-F1 0.687 (0.635-0.729); argmax agreement 98.9% |
| Noise robustness (AFDB + NSTDB test half, stream-filtered protocol as trained), AF AUROC (windows flagged Noisy) | em 24 dB 0.966 (5%), 12 dB 0.964 (6%), 6 dB 0.935 (19%), 0 dB 0.761 (98%), -6 dB 0.601 (100%); ma 6 dB 0.931 (23%), 0 dB 0.767 (89%); bw 6 dB 0.936 (27%), 0 dB 0.796 (97%) |

Intervals are 95% percentile bootstrap CIs resampling whole records (1,000 resamples, seed
20261014): 23 AFDB records and the CinC test records. With 23 records the AFDB intervals are wide
and the sensitivity could plausibly be anywhere from 0.75 to 0.94.

## The numpy forward pass (backend: `tier_b/rhythm_cnn.py`) and its parity

The backend runs the model with numpy only (FP32, or INT8 by QDQ fake-quantisation): no ONNX
Runtime, no MindSpore. Parity is pinned on logits against `golden.npz` (ONNX Runtime outputs on
ten seeded synthetic windows chosen to drive activations negative, above 6 and past the INT8
ranges; all four classes occur).

| Pair | Measure | Result |
|---|---|---|
| numpy FP32 vs ONNX Runtime FP32 | max abs logit difference | 2.9e-6 on the golden windows (3.8e-6 on 720 real AFDB windows, run once at development, not committed); test bound 2e-5 |
| numpy INT8 vs ONNX Runtime INT8 | logit difference (output step 0.0730) | 0 on the golden windows; on the 720 real windows 0.5% of logits differ by one step, none by more; test: at most one step and at least 90% exactly equal |
| torch FP32 vs ONNX Runtime FP32 | max abs logit difference | 4.8e-6 |
| INT8 vs FP32 | argmax agreement | 98.9% (CinC test windows) |
| MindSpore Lite FP32 / INT8 | not measured | gated on the user's approval; no conversion claim is made |

CPU time of the whole labeller (band-pass, normalisation, forward) per 10 s window, numpy, one
thread, Apple M4: about 2.7 ms FP32 and 2.9 ms INT8 (ONNX Runtime alone: 0.45 / 0.14 ms).

## Limitations (read before quoting any number)

- Not validated on chest-patch, ward or Philippine data; the sources are a handheld recorder
  (CinC) and Holter (AFDB).
- The CinC split is by record, not by patient (identifiers unavailable): possible optimistic
  leakage. `Other` and `Noisy` are weak classes.
- AFDB windows require >= 90% of one rhythm label, so transitional windows are excluded (easier
  than streaming); two of its 25 records have no signal files and are not counted.
- NSTDB train and test noise halves come from the same three noise records; real patch artefacts
  differ.
- AF sensitivity depends on the threshold: at argmax it was 0.70.
- Single lead only; the head is four-class (N, AF, Other, Noisy), so there is **no PVC or
  ectopy metric** and no beat localisation yet.
- **No RR-irregularity baseline** has been run on AFDB: whether this CNN beats a simple
  RR-interval AF rule on the same windows is untested, so no claim of added value over one is made.
- **The M3 exit gate is not met by this model or this card.** Outstanding at least: a PVC
  metric, an RR-irregularity baseline comparison and MindSpore Lite parity; the Evaluator's gate
  decides, and nothing here claims it.
- A window needs 10 s of gap-free signal: a patch with frequent dropouts will refuse most windows
  (coverage is reported, never hidden).

## Reproduce

`training/rhythm_head.py` (prep, train, eval, opt, export; Python 3.11, torch 2.14.1, numpy
2.4.6, scipy 1.17.1, wfdb 4.3.1, onnx 1.23.2, onnxruntime 1.31.0; seed 20261013), then
`training/export_numpy.py` writes `weights.npz` and `golden.npz`. Data are fetched at run time by
`training/fetch_data.py` (checksum-verified) and never committed.
