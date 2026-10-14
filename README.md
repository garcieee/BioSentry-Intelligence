# BioSentry

A ranked early-warning list for hospital wards in the Philippines.

BioSentry answers one question: *of your twenty patients, see this one first.* It takes
vital signs, adds what the hospital already knows (diagnosis, labs, and two values a nurse
types in: blood pressure and level of consciousness) and puts every patient on one ranked
list, one screen per clinician.

The list is sorted by **NEWS2**, a published bedside early-warning score (Tier A). A patient
who meets a NEWS2 trigger sits above one who does not. Tiers B and C (mechanism findings and an
outcome model) are not part of the scoring: what the screens show for them is demo content.

**This is not a diagnosis system.** It ranks and displays. A human decides.

## Run it

You need Python 3.11, Node.js `^20.19` or `>=22.12`, and git, make and curl.
From the repository root:

```bash
python3.11 -m venv backend/.venv
make be-install PYTHON=backend/.venv/bin/python
make web-install
make dev PYTHON=backend/.venv/bin/python
```

Open [http://localhost:5173](http://localhost:5173), choose a department and a clinician, and
sign in with any passphrase. Ctrl-C stops both servers. Whatever you enter is kept in memory
and is gone when the API restarts.

If a port is busy, `make dev` stops and says so. Pick other ports and open the web one:

```bash
make dev PYTHON=backend/.venv/bin/python WEB_PORT=5200 API_PORT=8100
```

Other commands, configuration, the project layout and the design notes are in
[DEVELOPMENT.md](DEVELOPMENT.md).

## What you will see

- **Sign-in:** pick a department and a clinician profile. This build accepts any passphrase.
- **Ward:** patients in priority order, each with its score and why. A patient the system
  cannot score is listed as NOT RANKED, with the reason and what to record to fix it.
- **Patient detail:** the score and what drives it, vitals and labs with where each value
  came from, notes, and trend charts.
- **Station:** admit a patient, enter lab results, or upload a document (extraction is a
  placeholder).

## Status

**Built**, on synthetic data:

- The dashboard and an API, with NEWS2 and the escalation rules computed on the server.
- Each clinician sees only their own patients, and every view is audited.
- Tested building blocks for Tier B signals (heartbeat detection, heart-rate variability,
  respiratory rate, perfusion index), not yet connected to the scoring or to a device.

**Pending:** Tier B and C in the scoring, trained models, anything measured on real patients,
a sensor pipeline, a database, real authentication, document extraction.

This repository makes no claim about clinical performance. The scores are a published rule
applied to made-up patients.

## Rules the system keeps

- **I1** Missing is missing: nothing is imputed or defaulted to zero.
- **I2** Every value carries where it came from: source, tier, time, quality.
- **I3** Tiers stay separate: Tier A sorts; Tier C never sorts and never alerts.
- **I4** Abstention is an output: NOT RANKED is a row with a reason and an instruction.
- **I5** No training on BioSentry patients: local data calibrates and validates only.
- **I6** The synthetic flag propagates: every fixture record says `synthetic: true`.
- **I7** Privacy (RA 10173): one screen per clinician, their patients only, audit on every view.
- **I8** Transport: BLE to a gateway, then Wi-Fi or 4G to the cloud. NB-IoT is excluded.

## Before you expose it anywhere

- **Synthetic data only.** No real patient data exists in this repository.
- **Identity is a stub.** The sign-in token *is* the clinician id, so anyone who can reach the
  API can act as any clinician. The API listens on `127.0.0.1` only and refuses another address
  unless started with `--allow-remote`. Do not put it on a network.
- **One process.** State lives in memory, so the API refuses to start with more than one worker.

## Licence

Competition entry for the Huawei ICT Competition Innovation Track. No real patient data exists in this repository.
