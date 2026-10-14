# Synthetic ward (I6)

Everything in this folder is synthetic. No real patient, name, bed or measurement exists
here; every record carries `synthetic: true`, and the file is never training data (I5).

`synthetic.json` is generated, not hand-edited:

    make data                      # PYTHON=backend/.venv/bin/python for a local venv

- Source: scripted scenarios in `backend/src/biosentry/sim/scenarios.py`, run through a
  seeded generator (`generator.py`) and assembled into contract records by `assemble.py`.
- Same seed, byte-identical file (default seed `20260903`, fixed `as_of`, no wall clock).
- Scores, ranks, trends and escalation reasons are not scripted: they are computed by the real
  `news2()` and the arbiter. The scripts only say how each vital moves.
- Gaps are `null` (never zero, never filled). A missing reading is an absent measurement
  with a reason.
- Tier B and Tier C content is demo content: scripted, `tier_status` reads "(demo)", and it
  never reaches the arbiter or the rank.
- `py-test` fails if this file differs from what the generator writes.

Layout: `ranked` (arbiter order), `abstained` (NOT RANKED rows), `details` (6-hour history and
tier breakdown per ranked patient), `notes`, and `labels` (the script's ground truth).
