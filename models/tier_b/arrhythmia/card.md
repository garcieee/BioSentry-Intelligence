# Tier B arrhythmia head (scaffold)

| | |
|---|---|
| id | `tier_b/arrhythmia` |
| tier | B (mechanism finding) |
| status | scaffold: interface only, no model, no weights |
| licence | unverified |

## What exists

`backend/src/biosentry/domain/scoring/tier_b/interface.py`: a window labeller protocol, a
registry, and an `Unimplemented` labeller that returns `NotComputed("not_implemented")` for
every window. Nothing is fabricated.

## What a real model must provide before it leaves scaffold

- A registry entry with the sha256 of its artifact, its corpus and a verified licence URL
  (or `unverified`, which can never be production).
- `fs`, `window_s` and a validity mask; a refusal (`NotComputed`) for any window without
  enough valid signal. Gaps are never imputed and never counted as normal.
- Per-window labels and a burden defined as valid positive windows over valid windows,
  reported with its coverage.
- Metrics on a held-out public set, and on the synthetic generator's ground truth, with
  evidence language only (no claim from synthetic or foreign data).
