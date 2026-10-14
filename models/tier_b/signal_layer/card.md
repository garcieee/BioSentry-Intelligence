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
| `robust_baseline`, `robust_z` | in-admission median/MAD and z | `baseline_not_established`, `baseline_has_no_spread`, `value_not_finite` |
| `pi_window` / `compute_pi` | perfusion index (100 x AC / DC, window median), pulse rate | `too_few_valid_pulses`, `low_signal_quality`, `dc_not_positive`, `pulse_rate_disagrees_with_ecg` |
| `rr_windows` | breaths/min, which estimators agreed, spread, how many voted | `insufficient_estimators`, `estimators_disagree`, `estimators_ambiguous` (two different agreeing pairs: no guess) |

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
8. **Scorer fingerprint.** `SCORER_MODULES` (tables, news2, arbiter; `test_cache` pins it) is
   what the snapshot cache hashes. These Tier B modules are not hashed because Tier B does not
   feed a decision yet; when Tier B is wired into scoring its modules must join `SCORER_MODULES`.

## Design parameters (from the literature or tuned on synthetic signals; none validated on patch data)

| Stage | Parameter | Value | Basis |
|---|---|---|---|
| ECG beats | smallest usable run searched | 3 s | design |
| ECG beats | refractory period | 0.25 s | design |
| ECG beats | QRS threshold | 0.2 x median of the strongest tenth of 0.25 s block maxima of slope energy | design, tuned on synthetic ECG |
| ECG beats | per-beat template correlation to count as valid | at least 0.6 (window 0.2 s before to 0.4 s after the R peak) | design |
| HRV | plausible interval | 0.3-2.0 s | design |
| HRV | ectopic interval | more than 20% from the median of up to 5 neighbours each side | design |
| HRV | irregular rhythm | ectopic share of plausible intervals above 30% | design |
| HRV | valid NN needed | RMSSD 10 s, SDNN 30 s | Munoz 2015, PLoS One 10(9):e0138921 |
| HRV | NN coverage / longest gap | at least 75% / at most 20 s | Cajal 2022, Sensors 22(15):5774 (2 min segments; its time-domain limit is 35% missing, RMSSD alone 25%) |
| Burden | threshold / minimum coverage | 110 bpm / 50% of minutes valid | design |
| Baseline | horizon / minimum valid minutes | last 360 min / 60 | design |
| PPG pulses | smallest usable run / refractory / foot search | 5 s / 0.3 s / 0.6 s | design |
| PPG pulses | peak threshold / template correlation | 0.35 x typical pulse amplitude / at least 0.7 | design |
| Perfusion index | valid pulses needed / valid share | 10 / at least 50% | design |
| Perfusion index | pulse rate vs ECG rate | within 20% | design |
| Perfusion index | definition | AC = smoothed peak minus the minimum 0.6 s before it; DC = raw mean over 1 s each side; 80 ms moving average; median over valid pulses | design; pinned to 1e-9 relative |
| Perfusion index | accuracy against the generator's known AC/DC | within 12% (reads 5-10% low on 90 ms pulses; 0.82 of truth on 40 ms pulses) | design tolerance; synthetic signals only |
| HRV | SDNN and RMSSD against exact interval series | within 0.01 ms; SDNN uses n - 1; RMSSD never differences across an excluded interval | design; synthetic exact series |
| RR | band | 6-30 breaths/min | plausible adult range |
| RR | agreement | within 3 breaths/min, at least 2 of 3 estimators; two different agreeing groups are refused (separate pairs and overlapping triples too) | design |
| RR | spectral prominence (peak / mean band power) | at least 8 | tuned: noise alone median 3.8, max 7.1; 6 gave false votes |
| RR | valid beats needed / accelerometer minimum run | 8 / 20 s | design; the longest run must reach about 30 s at 10-25/min (20 s at 30/min): only an edge gap up to about 2 s keeps the vote in a 32 s window, see Limits |
| RR | channel coverage floor to vote | 50% of the window | design |

## Evidence

Pipeline checks on exact synthetic ECG, PPG and accelerometer signals; **not a performance
claim**. R-peak F1 1.00 clean, at 0.08 mV noise and at 32-150 bpm; 0.99 with PVCs; HRV and RR
refuse rather than guess at 0.15 mV noise. The test suites are mutation-checked (deliberate faults
are injected into temporary copies and each must fail a test) and a structural test fails if any module under `tier_b/` imports
SciPy or pandas or uses interpolation, resampling or fill functions.

## Limits

- Not tested on chest-patch signals, ward patients or Philippine patients; skin tone effects on
  PPG are unmeasured.
- HRV is refused in irregular rhythm (AF): it is not meaningful there.
- PPG-derived values depend on the front end; automatic gain or DC cancellation changes the
  perfusion index and is not corrected.
- Respiratory rate from ECG or PPG amplitude is a weak channel by nature; the gate refuses
  more often than it reports.
- **The accelerometer vote needs a contiguous run of about 30 s (rate-dependent).** Its spectral
  prominence (peak over mean band power) of a clean tone grows with run length, so the gate of 8
  is crossed only at about 30 s for breathing rates of 10-25 per minute (28-29 s at 8 and 28;
  measured), whatever the amplitude, and the estimator uses the longest gap-free run. At 30 per
  minute, on the band edge, 20 s is enough and the 20 s minimum run is what binds. In a 32 s
  window only an edge gap of up to about 2 s keeps the vote (more than about 2 s abstains), and
  any gap in the middle, however short, silences it. Consequence: a window with a gap loses its
  third vote and the 2-of-3 agreement refuses more often (`NotComputed`) than the 20 s rule
  suggests. A 64 s window tolerates a 6 s gap because a 30 s or longer run survives (tested).
  Measured on synthetic signals; real noise only lowers prominence.
- **Freedom to operate not cleared**: respiratory-rate-from-ECG/PPG methods fall under an
  Oxford patent (US11103155B2, to about 2038). Research and competition use only until cleared.
