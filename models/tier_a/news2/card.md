# NEWS2 (Tier A)

| | |
|---|---|
| id | `tier_a/news2` |
| tier | A (deterministic; no learned weights, no artifact) |
| code | `backend/src/biosentry/domain/scoring/tier_a/` (`tables.py`, `news2.py`) |
| status | implemented, not validated on local data |
| licence | unverified (RCP publishes NEWS2 for clinical use; terms not confirmed in this repo) |

## Source

Royal College of Physicians. *National Early Warning Score (NEWS) 2: Standardising the
assessment of acute-illness severity in the NHS. Updated report of a working party.* London:
RCP, 2017. Tables transcribed from the published charts:

- NEWS2 chart 1, the NEWS scoring system: rcp.ac.uk/media/alxev00t/news2-chart-1_the-news-scoring-system_0_0.pdf
- NEWS2 chart 2, NEWS thresholds and triggers: rcp.ac.uk/media/2acdezkd/news2-chart-2_news-thresholds-and-triggers_0.pdf

Published tables, unmodified, no local tuning. The tables in `tables.py` are the single
source for scores, band labels and the reason strings shown to clinicians.

## Inputs

Respiratory rate, SpO2, SpO2 scale (1 or 2, an explicitly recorded value that is never
assumed), supplemental oxygen (air or oxygen), systolic blood pressure, heart rate, level of
consciousness (ACVPU) and temperature. Scale 2 applies only on a clinician's recorded decision
for confirmed hypercapnic respiratory failure.

## Scoring

| Parameter | 3 | 2 | 1 | 0 |
|---|---|---|---|---|
| Respiratory rate (/min) | ≤8, ≥25 | 21-24 | 9-11 | 12-20 |
| SpO2 scale 1 (%) | ≤91 | 92-93 | 94-95 | ≥96 |
| SpO2 scale 2 (%) | ≤83, ≥97 on oxygen | 84-85, 95-96 on oxygen | 86-87, 93-94 on oxygen | 88-92, ≥93 on air |
| Supplemental oxygen | | oxygen | | air |
| Systolic BP (mmHg) | ≤90, ≥220 | 91-100 | 101-110 | 111-219 |
| Heart rate (/min) | ≤40, ≥131 | 111-130 | 41-50, 91-110 | 51-90 |
| Consciousness | new confusion, V, P or U | | | Alert |
| Temperature (°C) | ≤35.0 | ≥39.1 | 35.1-36.0, 38.1-39.0 | 36.1-38.0 |

Total 0-4 low, 5-6 medium, 7 or more high. A single parameter scoring 3 is an independent
trigger (low-medium, urgent ward-based response) and is reported even inside a higher total.
Maximum 20.

## Rules this implementation adds

- **Abstention.** Any input missing, non-finite or physically impossible returns
  `News2Abstained` naming it. Nothing is imputed, defaulted or clamped (I1, I4).
- **Rounding.** Half-up before banding, with `Decimal` (not `round()`): integers for
  respiratory rate, SpO2, systolic BP and heart rate; one decimal for temperature (PLAN D13).
  The RCP charts give no rounding rule.
- **Shows its work.** Every result lists each parameter's value, band and score, and reasons
  built only from the tables.

## Limits

- Deterministic transcription of a published score. No claim about performance on this
  population or on synthetic data.
- Scope per the RCP report (adult patients). The scorer does not check age.
- Physical-impossibility checks are guards, not clinical plausibility ranges; plausibility
  belongs to the signal quality gate. Exactly 0 is scored for heart rate and respiratory rate
  (asystole and apnoea are real) but rejected for SpO2, temperature and systolic BP, where 0
  is what a zero-fill looks like.
