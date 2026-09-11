# BioSentry Intelligence

A clinical early-warning system for **general wards** in Philippine hospitals, where
nurse-to-patient ratios of 1:20 or worse make scheduled observation rounds
structurally unable to catch patients who are quietly deteriorating.

## Scope

Cardiovascular deterioration first, on general wards, plus the two windows where
already-monitored patients go dark:

- **Post-ICU step-down** — the patient moves from continuous ECG to a four-hourly chart
- **First 48h after surgery** — myocardial injury here is overwhelmingly asymptomatic

Not cardiovascular/telemetry wards. The premise is covering beds that have no
continuous monitoring at all.

## Inputs

**Wearable adhesive patch** — PPG, single-lead ECG (with inter-beat intervals), skin
temperature, accelerometry. Continuous.

**Hospital-held data** — admitting diagnosis, ejection fraction, cardiac biomarkers,
electrolytes, renal and haematological labs. Episodic.

**Nurse-entered** — blood pressure, level of consciousness.

Every stored value carries its source (DEVICE / NURSE / LAB), device ID, and
measurement time. Lab values also carry collection age. Provenance is displayed, not
hidden — clinicians judge trust from it.

## Station (admission)

DOH-compliant face sheet: name, PhilHealth PIN, chief complaint, attending physician,
initial vitals. PhilHealth PIN is **sensitive personal information** under RA 10173 and
must be access-controlled and audit-logged accordingly.

Once admitted, the patient sits in **ABSTAINED** state until the patch is applied and
signal is verified.

Document scanning / auto-extraction is **v2**. It is OCR, a second AI modality, and is
out of MVP scope.

## Ward view

Live-sorted list of patients, **filtered to only the patients under the logged-in
clinician's care**. This filter is a usability decision *and* a Data Privacy Act access
control. It is enforced server-side on every API call, never as a client-side view.

Patients with missing required inputs are pulled out of the ranking entirely and shown
separately with the specific missing measurement named. Never impute.

## The three tiers

Assessed independently, never blended into a single number. The nurse sees all three so
she can interrogate and challenge each one.

**Fuse inputs, never outputs.** Tier C may read raw and derived features. It may never
read another tier's verdict.

### Tier A — NEWS2 (deterministic)

Standard National Early Warning Score from HR, RR, SpO2, temp, BP, consciousness.
Published lookup tables, unmodified, no local tuning. Drives the default sort order.
Threshold crossing escalates unconditionally.

### Tier B — Mechanism findings

Answers *through which physiological pathway is this patient failing?* Output is a list
of named findings with their own units and direction. **Not a score. Not bars on a
shared scale** — 12% arrhythmia burden and a 0.30 perfusion index are not comparable
quantities.

*Primary device axes:*
- Arrhythmia burden — **this is ML**: beat classification off the single-lead ECG. It is
  Tier B's only ML component and is why the patch needs ECG, not PPG alone.
- Respiratory rate vs the patient's **own rolling baseline** (statistics, not a model)
- Perfusion index trend

*Primary lab substrate* (published thresholds and trends, **not ML**):
- Troponin trend — highest-value axis in the post-op window
- K+ / Mg read against arrhythmia burden
- Creatinine into KDIGO staging
- Lactate corroborating perfusion

*Secondary axes:* HRV (SDNN / RMSSD), KDIGO stage. HRV depends on patch firmware
exposing inter-beat intervals — if unavailable, the axis is absent, not estimated.

A significant finding raises priority and attaches a clinical pathway (e.g. "renal",
"perfusion", "arrhythmic").

### Tier C — Outcome model (ML)

Calibrated probability of deterioration within a stated **1–4 hour horizon**, with SHAP
attributions in clinical language. Gradient-boosted trees over windowed features.

Reads the shared feature store directly: vitals trajectories, baseline deviations,
arrhythmia burden over time, serial labs, admission context. Merging live telemetry with
labs is correct and is the point.

Never reads Tier A or Tier B **verdicts**. Derived features are shared; the judgement of
whether a finding was "significant" is not.

May raise priority. May **never** lower it below Tier A's position.

## Notes layer (v2)

Local SLM on the ward box reads nursing and doctor notes on save. Fixed extraction
schema: concern present (bool), pathway (closed set), trigger phrase (verbatim).

Separate **escalation-only** input to the arbiter. It may raise a patient and attach the
trigger phrase. It is **not** a Tier B axis, contributes **no** score, and feeds **no**
feature into Tier C — notes are written after a nurse has already noticed something, so
training on them leaks the label. Quiet by default: most notes do nothing.

## Escalation arbiter

The only component permitted to change displayed priority.

1. Tier A threshold met → escalate unconditionally
2. Tier C may raise, never lower below Tier A
3. Tier B significant finding → raise + attach pathway
4. Notes layer concern → raise + attach trigger phrase *(v2)*
5. Missing required input → **NOT RANKED**, naming what is missing. Never impute. An
   abstaining tier contributes no default value.

## UI principles

- **No rank badge, no single tier badge in the patient header.** Put the *reason* there:
  why this patient is up and which layer raised them.
- Tier B renders as a findings list with units and direction arrows, never progress bars.
- SHAP bars appear in Tier C only — that is the one place a shared scale is real.
- Provenance tags and lab collection age stay visible on every value.
- Audience is clinicians who want everything in their face. **Density over minimalism.**
  Do not hide detail behind progressive disclosure.

## Why this helps

A single merged score is a black box a nurse cannot challenge. Three separate signals
give her three independent reasons to act or to push back. She sees *why* a patient is at
the top of the list, not just that they are.
