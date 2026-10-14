# Tier B signal layer (M2: classical, no learned weights)

| | |
|---|---|
| id | `tier_b/signal_layer` |
| tier | B (mechanism measurements; not a score, never on a shared scale) |
| code | `backend/src/biosentry/domain/scoring/tier_b/` (`ecg.py`, `hrv.py`, `burden.py`, `ppg.py`, `respiration.py`, `dsp.py`) |
| status | implemented, not validated on patch, ward or Philippine data |
| licence | unverified (own code; the RR methods carry an uncleared Oxford patent, see Limits) |
| runtime | Python 3.11 and numpy 2.4.6 only; no SciPy, pandas or NeuroKit2 |

## What it provides

Pure functions that return `Computed(value, provenance, window)` or `NotComputed(reason)`.
Nothing is interpolated, resampled or filled; a gap is a gap (I1).

| Function | Output | Refuses with |
|---|---|---|
| `detect_beats` | R-peak times, per-beat validity, run id, R amplitude | (a run under 3 s yields no beats) |
| `hrv_window` / `compute_hrv` | RMSSD, SDNN, mean HR, n NN, excluded count, NN coverage | `gap_longer_than_20s`, `irregular_rhythm`, `insufficient_valid_nn`, `nn_coverage_below_75pct`, `insufficient_consecutive_nn` |
| `hr_burden` | minutes at or above 110 bpm over **valid** minutes, with coverage | `coverage_below_minimum`, `no_minutes` |
| `robust_baseline`, `robust_z` | in-admission median/MAD and z | `baseline_not_established`, `baseline_has_no_spread` |
| `pi_window` / `compute_pi` | perfusion index (100 x AC / DC, window median), pulse rate | `too_few_valid_pulses`, `low_signal_quality`, `dc_not_positive`, `pulse_rate_disagrees_with_ecg` |
| `rr_windows` | breaths/min, which estimators agreed, spread, how many voted | `insufficient_estimators`, `estimators_disagree` |

## Wire-up notes (for whoever integrates this into the scoring service)

1. **The perfusion index must receive the ECG rate.** `expected_hr_bpm` is optional in the
   signature, but a periodic artefact larger than the pulse (steady-cadence motion) is otherwise
   detected instead of the pulse and yields a plausible, valid-looking number. Always pass the
   ECG heart rate for the same window; the pipeline gets a test that PI is never emitted
   without it.
2. **Carry the refusal, not a default.** A `NotComputed` reason reaches the clinician as the
   reason a value is absent. No consumer may substitute 0, the previous value or a population
   mean.
3. **Windows.** HRV: 60 s or longer ECG windows. RR: 32 s windows; ECG, PPG and accelerometer
   share `window_s` and a start time. Coverage and `quality` (`ok` / `degraded`) travel with
   every value; show a degraded value as degraded.
4. **Baseline is in-admission and not stored.** It is computed from the patient's stored
   per-minute rows each time; there is no baseline table and nothing crosses admissions.
5. **Arbiter rule 3 stays inert.** These are Tier B measurements. Do not map them to
   `EscalationReason`s, `significant` flags or pathways until the user rules on Tier B
   findings (PLAN D11: demo B/C content never feeds the arbiter).
6. **Numeric environment.** Python 3.11 with numpy 2.4.6 as pinned. Other numpy or Python
   versions are untested; the machine's system Python 3.14 with numpy 2.2.6 corrupted large
   arrays during development and must not be used for numeric runs.
7. **Cadence assumed.** ECG 250-500 Hz, PPG about 100 Hz, accelerometer 25 Hz or more,
   per-minute derived vitals for burden and baseline.

## Design parameters (from the literature or tuned on synthetic signals; none validated on patch data)

| Parameter | Value | Basis |
|---|---|---|
| RMSSD / SDNN minimum valid NN | 10 s / 30 s | Munoz 2015, PLoS One 10(9):e0138921 |
| Missing-beat and gap limits | 25% missing, bursts over 20 s | Cajal 2022, Sensors 22(15):5774 (2 min segments; its time-domain limit is 35%, RMSSD alone 25%) |
| Ectopic interval | more than 20% from the local median | design |
| QRS threshold | 0.2 x median of the strongest tenth of block maxima | design, tuned on synthetic ECG |
| RR estimator agreement | within 3 breaths/min, at least 2 of 3 | design |
| RR spectral prominence | peak / mean power of at least 8 | tuned: noise alone median 3.8, max 7.1; 6 gave false votes |
| PPG pulse rate vs ECG rate | within 20% | design |

## Evidence

Pipeline checks on exact synthetic ECG, PPG and accelerometer signals; **not a performance
claim**. R-peak F1 1.00 clean, at 0.08 mV noise and at 32-150 bpm; 0.99 with PVCs; HRV and RR
refuse rather than guess at 0.15 mV noise. The test suites are mutation-checked (M2a seven
faults, M2b twelve) and a structural test fails if any module under `tier_b/` imports
SciPy or pandas or uses interpolation, resampling or fill functions.

## Limits

- Not tested on chest-patch signals, ward patients or Philippine patients; skin tone effects on
  PPG are unmeasured.
- HRV is refused in irregular rhythm (AF): it is not meaningful there.
- PPG-derived values depend on the front end; automatic gain or DC cancellation changes the
  perfusion index and is not corrected.
- Respiratory rate from ECG or PPG amplitude is a weak channel by nature; the gate refuses
  more often than it reports.
- **Freedom to operate not cleared**: respiratory-rate-from-ECG/PPG methods fall under an
  Oxford patent (US11103155B2, to about 2038). Research and competition use only until cleared.
