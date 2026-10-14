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
  Values that overflow float32 (in the input or after filtering) or logits that are not finite are
  refused with their own reasons: a label never comes from a NaN.
- Preprocessing (per window, so windows stay independent): causal Butterworth band-pass 0.5-40 Hz
  (order 2 per band edge, two second-order sections) with zero initial state, then median/MAD
  normalisation (MAD x 1.4826, +1e-6, clipped at +/-10). Measured against the stream-filtered
  distribution it was trained on, per-window filtering changed AFDB AF AUROC from 0.9655 to 0.9666
  and CinC macro-F1 from 0.681 to 0.683, so there was no retrain.
- Output: 4 logits (N, AF, Other, Noisy). AF operating point: p(AF) >= 0.20 among accepted
  windows, chosen on the CinC validation split only.
- Size: 88,612 weights after folding BatchNorm into the convolutions (88,972 parameters before);
  FP32 ONNX 350 KB, INT8 QDQ (static, per-channel) 110 KB. Speed and memory: see the latency table.
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
| MIT-BIH Arrhythmia Database (48 half-hour 360 Hz recordings; lead MLII) | not used to train, tune or select the head: R-peak detector check of the RR baseline on the 22 DS1 records only. Paced records 102, 104, 107, 217 are out by convention, and 202 is out because it is the same subject and tape as 201; DS2 is untouched | 1.0.0 (2005-02-24), https://doi.org/10.13026/C2F305 | https://physionet.org/content/mitdb/view-license/1.0.0/ |

Attribution (required): Clifford GD et al., "AF classification from a short single lead ECG
recording: the PhysioNet/Computing in Cardiology Challenge 2017", CinC 2017, DOI
10.22489/CinC.2017.065-469; Moody GB, Muldrow WE, Mark RG, "A noise stress test for arrhythmia
detectors", Computers in Cardiology 1984;11:381-384; Moody GB, Mark RG, "A new method for detecting
atrial fibrillation using R-R intervals", Computers in Cardiology 1983;10:227-230; Moody GB, Mark
RG, "The impact of the MIT-BIH Arrhythmia Database", IEEE Eng in Med and Biol 2001;20(3):45-50; and
Pollard T
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
| CinC 2017 test-split records (internal; 4,683 windows) | macro-F1 0.683 (95% CI 0.630-0.726); F1 N 0.847, AF 0.765, Other 0.654, Noisy 0.465; AF AUROC 0.965 (0.938-0.985); AF ECE 0.019 |
| **AFDB, external** (83,863 windows, 23 records, never trained on) | AF AUROC 0.967 over all windows (0.944-0.984; 0.979 among accepted); at p(AF) >= 0.20, among accepted windows: sensitivity 0.846 (0.745-0.936), specificity 0.972 (0.940-0.991), PPV 0.954 (0.894-0.987) at AFDB's 40.5% AF prevalence; 5.2% of windows refused as Noisy (3.3-7.5%); per-record burden MAE 0.076 (0.035-0.124), Pearson r 0.940; worst record 05121 |
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

Timing of both paths is in the next two sections.

## Against a classical RR-irregularity rule (same AFDB windows)

The gate asks what the CNN adds over a plain rule on the beat-to-beat intervals. The baseline is
`training/rr_baseline.py`: a numpy R-peak detector (checked on MIT-BIH Arrhythmia DS1 only:
sensitivity 0.980 and PPV 0.993 within 150 ms, 49,829 of 50,860 beats in 22 records), four
interval statistics per 10 s window (normalised RMSSD, coefficient of variation, turning-point
ratio, and the median absolute successive difference over the median interval), and a refusal for
fewer than 6 beats or a median interval outside 0.3-2.0 s (0.3% of AFDB windows; a refusal is never
scored as regular). The statistic and its threshold were chosen on the CinC 2017 validation windows
only, with the head's own rule (the smallest threshold that keeps specificity at 0.95 against N and
Other among accepted windows), and pinned in `training/rr_baseline_selection.json` before AFDB was
scored: the median-difference statistic, threshold 0.269 (validation AUROC 0.918, against 0.856,
0.840 and 0.792 for the other three).

AFDB, 83,863 windows in 23 records; record-level bootstrap, 1,000 resamples, seed 20261014.
Sensitivity, specificity and PPV are each method's own validation-chosen operating point, among the
windows it accepts. Retrospective, public data.

| | CNN head | RR rule | Paired difference, head minus rule |
|---|---|---|---|
| AF AUROC, all windows (a refusal ranks lowest) | 0.967 (0.944-0.984) | 0.925 (0.890-0.952) | +0.042 (+0.016 to +0.075) |
| AF AUROC, windows both accept (94.7%) | 0.979 (0.956-0.993) | 0.934 (0.900-0.960) | +0.045 (+0.021 to +0.076) |
| Sensitivity | 0.846 (0.745-0.936) | 0.223 (0.151-0.287) | +0.623 (+0.536 to +0.706) |
| Specificity | 0.972 (0.940-0.991) | 0.966 (0.955-0.975) | +0.007 (-0.028 to +0.029) |
| PPV (AFDB prevalence 40.5%, not a ward's) | 0.954 (0.894-0.987) | 0.815 (0.642-0.914) | +0.139 (+0.053 to +0.293) |
| Windows refused | 5.2% (3.3-7.5%) | 0.3% (0.1-0.6%) | |
| Per-record burden MAE | 0.076 (0.035-0.124) | 0.313 (0.206-0.421) | |
| Rule's sensitivity if its threshold is re-chosen on AFDB to match the head's specificity (descriptive, not an operating point) | | 0.138 (0.007-0.552) | |

Read with care. (1) The rule's threshold was set where "Other" rhythms (ectopy and other
arrhythmias) are as irregular as AF: on the CinC validation windows the rule reached sensitivity
0.243 at specificity 0.950 and the head 0.876 at 0.952, and the rule's AUROC is 0.958 against N but
0.842 against Other. (2) The rule has no quality gate of its own, while the head refuses 5.2% of
windows as Noisy; the paired AUROC on windows both accept is given for that reason.
(3) A 10 s window holds 6 to about 25 beats, short for an interval statistic, so this says nothing
about the rule on longer windows. (4) 23 records, one device, one population.

Disclosure: AFDB was never trained on or tuned on, but this head was scored on it repeatedly
(evaluation, the filter-variant check, the noise test); the only decision those runs informed was
"no retrain". Whether AFDB meets the gate's external-set requirement is the Evaluator's ruling, not
this card's.

## CPU latency and memory

Apple M4, one thread, batch 1, warm (200 calls), 3,000 timed calls, ONNX Runtime 1.31.0
(`training/bench_ort.py`: the network only, on the ten synthetic golden windows) and the backend's
numpy labeller (band-pass, normalisation and forward; 1,500 timed calls; a one-off script, not
committed). A patient minute is six non-overlapping windows. Peak RSS is the whole process
(interpreter, numpy or ONNX Runtime, model).

| Path | p50 per window | p95 per window | p50 / p95 per patient-minute | Peak RSS |
|---|---|---|---|---|
| ONNX Runtime FP32 (network only) | 0.225 ms | 0.227 ms | 1.35 / 1.36 ms | 57.8 MB |
| ONNX Runtime INT8 (network only) | 0.070 ms | 0.070 ms | 0.42 / 0.42 ms | 57.8 MB |
| numpy FP32 (whole labeller) | 1.40 ms | 1.41 ms | 8.39 / 8.48 ms | 47.6 MB |
| numpy INT8 (whole labeller) | 1.53 ms | 1.55 ms | 9.17 / 9.28 ms | 47.9 MB |

The figures this card quoted before (0.45 / 0.14 ms and about 2.7 / 2.9 ms) came from an informal
one-off run whose method was not kept; these replace them. The ward gateway's CPU class is not
measured, and no latency budget has been set.

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
- The RR-irregularity comparison above is on AFDB only (23 records, 10 s windows, one detector):
  nothing here extends it to ward or Philippine data.
- **The M3 exit gate is not met by this model or this card.** Outstanding at least: a PVC
  metric and MindSpore Lite parity; the Evaluator's gate decides, and nothing here claims it.
- A window needs 10 s of gap-free signal: a patch with frequent dropouts will refuse most windows
  (coverage is reported, never hidden).

## Reproduce

`training/rhythm_head.py` (prep, train, eval, opt, export; Python 3.11, torch 2.14.1, numpy
2.4.6, scipy 1.17.1, wfdb 4.3.1, onnx 1.23.2, onnxruntime 1.31.0; seed 20261013), then
`training/export_numpy.py` writes `weights.npz` and `golden.npz`. Data are fetched at run time by
`training/fetch_data.py` (checksum-verified) and never committed.

`training/rr_baseline.py` (`check-detector`, `select`, `score`) writes the baseline rows and
`training/rr_baseline_selection.json`; `training/bench_ort.py` writes the ONNX Runtime latency
rows. The numbers quoted in the last three sections are kept in `m3_exit_measurements.json` and
checked against this card by `backend/tests/unit/test_rr_baseline.py`.
