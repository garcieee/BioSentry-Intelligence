# Tier C outcome model (scaffold)

| | |
|---|---|
| id | `tier_c/outcome` |
| tier | C (outcome model) |
| status | scaffold: protocol only, no model, no weights |
| licence | unverified |

## What exists

`backend/src/biosentry/domain/scoring/tier_c/interface.py`: a `Predictor` protocol that takes
`TierCInput` (features only; it has no field that can carry a Tier A score, a Tier B finding
or an arbiter reason) and a `NoModel` predictor that returns `NotComputed`.

The arbiter's Tier C hook is inert: supplying a Tier C signal changes nothing in v1.

## What a real model must provide before it can raise a patient

- A registry entry with sha256, corpus and licence; calibrated probability with a stated
  forecast window; a current conformal certificate, or it stays display-only.
- Shadow mode first. It may raise priority and may never lower it below Tier A.
- Never reads another tier's verdict; never trained on BioSentry patients (I5).
