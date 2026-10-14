# M4 spec: Tier C outcome model, data, labels, features, leakage rules

Status: **spec only**. No credentialed data is in this repository and none may be (I5; PhysioNet
licence clause 6). This document is the contract for the future `training/` extraction and the
future `evaluation/` package; the leakage checks it names already run on the synthetic generator
(`backend/tests/support/m4_leakage.py`, `backend/tests/unit/test_m4_leakage.py`).

Claims language for anything produced from this spec: "retrospective, public data". Never
"validated", "beats NEWS2" or "hours earlier" (PLAN P10).

## 1. Unit and grid

- Unit: one patient stay on a ward or step-down unit.
- One prediction every 15 minutes (the generator's bin), starting 6 h after ward arrival so a
  full 6 h window exists; horizons 1, 2 and 4 h.
- A prediction at minute `t` may use only data whose **store time** is at or before `t`.

## 2. Label

- Composite event: unplanned ICU transfer from the ward or step-down unit, cardiac arrest, or
  death, inside the horizon. Comfort-care and do-not-resuscitate transitions are flagged and
  excluded from the positive class.
- **Never NEWS-defined**: a NEWS-based label favours Tier A by construction.
- Exclude windows that end within 1 h before a planned post-operative ICU admission; censor at
  discharge.
- Hand-audit 100 positive and 100 negative windows per corpus before the first training run
  and keep the audit sheet with the dataset card.

## 3. Features (shared feature store; NaN-native; no imputation)

Per vital (HR, RR, SpO2, temperature, systolic/diastolic BP, consciousness):

| Feature | Notes |
|---|---|
| last value, age since last observation | stale is reported as stale, never as current |
| median / min / max / slope over 1, 3 and 6 h | slope needs at least 10 valid points, else NaN |
| observation count and inter-observation gaps | observation timing is data (CONCERN-style), not imputed |
| delta against the rolling in-admission median/MAD | a pure function of the stored rows; never persisted |
| shock index at BP stamps | HR / SBP at the time of the nurse reading |
| `__missing` indicator | explicit; a missing value is NaN, never 0 |

Labs: last value, age, delta against the previous result, 24 h min/max (lactate, creatinine,
K, Na, Hb, WBC, troponin, BNP). Context: age, sex, admission type, comorbidity flags, hours
since admission or surgery, unit type.

**Forbidden inputs**: the NEWS2 score or any band, Tier B finding flags, KDIGO stage (raw
creatinine and its delta are allowed), arbiter output, rank, anything derived from the label.
Tier C fuses inputs, never outputs.

## 4. Domain gap, stated up front

Public ward corpora hold charted vitals, not patch signals. Tier C is trained on charted vitals
and labs. HRV, arrhythmia burden, perfusion index and personal baselines join later through
local calibration and validation only (I5). Closest ward proxies: eICU-CRD step-down stays and
INSPIRE post-operative wards. MIMIC-IV hospital-module vitals are ICU and ED only.

## 5. Splits

- Patient-level always (`assert_patient_level_split`).
- Leave-one-corpus-out across eICU-CRD, MIMIC-IV and INSPIRE (plus HiRID and AmsterdamUMCdb if
  access is granted); then a single, hash-locked, one-shot hold-out on an untouched corpus or
  an eICU hospital block.
- Temporal blocks for early stopping; never random row splits.

## 6. Model

LightGBM, exact-pinned, NaN-native. Monotone constraints only on distance-from-normal features,
not on U-shaped raw vitals. Probability calibration (intercept, slope, then isotonic or
Venn-Abers) on a held-out site; a Learn-then-Test certificate from held-out events; operating
point anchored to an alert budget (alerts per 100 patient-days). Tier C may raise a patient and
never lowers one below Tier A (PLAN ruling pending on README I3).

## 7. Evaluation (W4; Evaluator owns the bars)

- Primary: paired difference in recall@k per ward-shift at equal k against Tier A, with a
  patient-clustered bootstrap and a pre-set margin; otherwise Tier A keeps sorting.
- Comparators: NEWS2 computed from the charted vitals, a recalibrated NEWS2 + logistic arm,
  and Tier C with abstention falling back to NEWS2.
- Also: PPV@k, alerts per 100 patient-days, number needed to evaluate, lead time on detected
  events only, calibration slope / intercept / ICI, net benefit at budget thresholds, a
  coverage-risk curve for abstention, sex and age subgroups. Skin-tone effects on SpO2 and PPG
  cannot be measured in these corpora and must be measured locally.
- NEWS was validated on 24 h composites: a 1-4 h comparison is horizon-mismatched and must say so.

## 8. Leakage rules, as tests (not comments)

Implemented now on the generator; each future builder must pass them unchanged:

1. `assert_no_future_dependence`: replacing everything after `t` (NaN, huge garbage, reversed)
   leaves the features at `t` identical.
2. `assert_missing_stays_missing`: a vital with no data yields NaN value features and an explicit
   `__missing` flag; zero-filling fails the check.
3. `assert_no_verdict_features`: no feature name carries a verdict or outcome term.
4. `assert_patient_level_split`: no patient in both train and test.

Still to add with the real extractors: store-time versus chart-time check per corpus (MIMIC
`charttime` is not `storetime`), label-leak scan (no feature column correlates 1.0 with the
label), and the label-audit sheet.

## 9. Access, licence, lead time

- PhysioNet credentialing (CITI course, reference, per-dataset data use agreement) is the
  user's to start, for eICU-CRD, MIMIC-IV and INSPIRE; allow days to weeks. VitalDB is open
  (CC BY 4.0) but intra-operative.
- PhysioNet clause 6 limits use to scientific research: weights trained on these corpora get
  registry corpus-licence `restricted`, and commercial use needs written terms. No row-level
  data in the repository, ever.

## 10. Deliverables when access exists

Feature table, per-corpus extraction SQL, label audit sheet, dataset card, the leakage tests
bound to the real builders, then model, card and registry entry. Until then only this spec and
the generator-based tests ship.
