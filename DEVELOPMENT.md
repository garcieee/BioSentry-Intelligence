# Development

Reference detail for BioSentry. The [README](README.md) has the short version: what it is,
how to run it, and what to be careful of.

## Run options

| Want | Command | Notes |
|------|---------|-------|
| API and dashboard together | `make dev PYTHON=backend/.venv/bin/python` | API on `127.0.0.1:8000`, dashboard on `localhost:5173`. Ctrl-C stops both. |
| Other ports | `make dev PYTHON=... WEB_PORT=5200 API_PORT=8100` | The API allows exactly the dashboard's origin, so a taken port is an error, not a fallback. |
| API only | `make be-serve PYTHON=...` | Same launcher, `127.0.0.1:8000`. `python -m biosentry.api --help` lists the flags. |
| Dashboard only, on fixtures | `make web-install`, then `make web-dev` | With no `VITE_API_URL` the dashboard serves the committed synthetic dataset from the browser. |

Pass `PYTHON=backend/.venv/bin/python` to any backend target if your virtualenv is not the
active interpreter.

### About the API process

- **Identity is a stub.** The bearer token *is* the clinician id: anyone who can reach the
  port can act as any clinician. Real authentication replaces this before any non-synthetic
  use. The launcher binds `127.0.0.1`, prints a notice every time it starts, and refuses a
  non-loopback `--host` unless `--allow-remote` is given.
- **One process.** Repositories, the audit log and the snapshot cache live in that process's
  memory, so the API refuses to start with more than one worker (`--workers`,
  `WEB_CONCURRENCY`, `UVICORN_WORKERS` or `BIOSENTRY_WORKERS` above 1) and says why. Start it
  with `python -m biosentry.api` (what `make dev` and `make be-serve` do): it checks before
  binding a port and exits non-zero. Under `uvicorn --workers N` every worker refuses, but
  uvicorn's supervisor keeps respawning them.
- **Synthetic data only.** Every record carries `synthetic: true`.

## Configuration

Read once at start-up, from the environment. A combination the process cannot run safely
fails to start.

| Variable | Default | Meaning |
|----------|---------|---------|
| `BIOSENTRY_DATASET` | `data/synthetic/synthetic.json` | Dataset the in-memory repositories load |
| `BIOSENTRY_CORS_ORIGINS` | `http://localhost:5173,http://localhost:5174` | Browser origins allowed to call the API |
| `BIOSENTRY_WARD_TIME` | `dataset` | `dataset` freezes ward time at the dataset's `as_of`; `system` uses the real clock |
| `BIOSENTRY_CACHE` | `memory` | Per-patient score snapshots: `memory` or `none` (compute on every read) |
| `BIOSENTRY_CACHE_TTL_S` | `30` | Snapshot lifetime in seconds; refused above 60 (the staleness ceiling) |
| `BIOSENTRY_WORKERS` | `1` | Declare the number of serving processes when it cannot be detected |

## Makefile commands

| Command | What it does |
|---------|-------------|
| `make dev` | API and dashboard together |
| `make be-install` | Install the backend and its dev tools (pinned by `backend/constraints.txt`) |
| `make be-serve` | API only, on `127.0.0.1:8000` |
| `make be-lint` / `make be-fmt` | Ruff, format check and mypy / apply fixes and format |
| `make be-test` | pytest |
| `make be-check` | `be-lint` and `be-test` |
| `make data` | Regenerate the committed synthetic dataset (a test fails if it is stale) |
| `make contract` | Regenerate `contracts/openapi.json` and `frontend/src/types/generated.ts` from the schemas |
| `make contract-check` | Schema tests, regenerate, fail if the committed files differ (CI: `contract-drift`) |
| `make http-contract` | One contract suite against the fixture provider and the running API |
| `make web-install` | Install frontend dependencies (`npm ci`) |
| `make web-dev` | Dashboard only, on fixtures, with hot reload |
| `make web-build` | Production build (typecheck and bundle) |
| `make web-typecheck` | TypeScript in check mode (`make check` runs this) |
| `make web-lint` / `make web-test` | ESLint / Vitest |

## What you will see, in detail

### Sign-in

A four-step flow: department (Nursing or Medical), clinician profile, passphrase, and
destination (Ward or Station). Five profiles are available, each assigned to specific
patients. This build accepts any passphrase. Live deployments would authenticate through the
hospital's identity provider.

### Ward view

The core screen. A ranked list of patients ordered by escalation level, then NEWS2 total,
highest first.

- **Status bar:** ward, operator, shift, and a live indicator
- **Summary cards:** patients ranked, not ranked, trending up, active scoring tiers, and
  pending tiers
- **Ranked rows:** rank, NEWS2 score, trend direction, patient identity, admitting context,
  driving mechanism, vitals (with provenance), lab freshness, and which tier the sort ran on
- **Not ranked section:** patients the system cannot score, each with a reason and an
  instruction (for example "Systolic BP missing: Record a blood pressure"). With the API
  running, each row has a "Record vitals" form: bounded fields, an echo of what will be
  stored, and the server's reason if it refuses a value. The ward is fetched again after a
  record and says where the patient now stands.

### Patient detail

Click any ranked row. Two-column layout: identity and tier breakdown on the left, vitals and
labs on the right. Every value shows its provenance source (device, nurse, lab) so a
clinician can tell a device-derived number from a nurse-typed one at a glance. Collapsible
panels for Tier A (NEWS2 with sparkline), Tier B (mechanism axes) and Tier C (outcome model);
the Tier B and C content is demo content. Slide-over drawers for clinical notes and vital
trend charts.

### Station

Nurse workstation with three tabs:

- **Admit patient:** DOH/PhilHealth-aligned admission form (identity, admission details,
  initial assessment)
- **Enter lab results:** manual entry for 17 lab fields grouped by section (cardiac
  biomarkers, electrolytes, renal, hematology, coagulation, liver, metabolic), in
  Philippine-standard units
- **Upload:** document upload with a review-and-confirm step before saving. Extraction is
  simulated on fixtures; the API answers 501 for it.

## Project structure

```
BioSentry-Intelligence/
  README.md                       Overview and how to run it
  DEVELOPMENT.md                  This file
  OVERVIEW.md                     Product scope and design notes
  Makefile                        Task runner
  .github/workflows/ci.yml        CI: checks, and one `ci-gate` job that requires them

  backend/                        Python 3.11 backend
    pyproject.toml                Direct dependencies, exact pins
    constraints.txt               Pins for the whole install
    src/biosentry/
      api/                        FastAPI app and the launcher (python -m biosentry.api)
      schemas/                    Pydantic models: the contract source of truth
      domain/                     NEWS2 (scoring/tier_a), the arbiter, Tier B signal code, registry
      services/                   ward, patients, scoring (uses the cache)
      repositories/memory/        In-memory store seeded from the dataset
      cache/                      Snapshot cache: protocol, in-memory TTL backend, keys
      core/                       Settings and the audit log
      sim/                        Seeded synthetic data generator
    tests/                        unit, contract, integration

  contracts/                      openapi.json and the TypeScript type generator
  data/synthetic/                 The committed synthetic dataset (generated; see its README)
  models/                         Registry and model cards (no trained weights)
  training/                       Offline training spike; not imported by the application

  frontend/                       React + Vite + TypeScript
    src/
      main.tsx, App.tsx           Bootstrap, routes, session state
      index.css                   Design tokens and global styles
      types/                      generated.ts (never edit) and index.ts
      data/fixtures.ts            Serves the synthetic dataset in fixture mode
      api/                        ApiProvider interface, fixture and HTTP providers, bounds
      components/                 Ward rows, vitals entry, charts, provenance display
      pages/                      SignIn, Ward, PatientDetail, Station
```

## Architecture

BioSentry was built **frontend first**. The ward row is the product; everything upstream
exists to fill it. The sequence:

1. **Design language:** tokens, not adjectives. Exact colours, type scale, spacing. (Done)
2. **Frontend on typed fixtures:** the real interface running on local data. (Done)
3. **Contract:** the Pydantic models are the source of truth; OpenAPI and the TypeScript types
   are generated from them and checked for drift in CI. (Done)
4. **Backend:** FastAPI serving the contract. Scoring runs on the server, scoped per
   clinician and audited, over in-memory repositories seeded from the synthetic dataset.
   (Done for the API; the database is pending)
5. **Pipeline:** sensor replay, quality gate, feature extraction, scoring from signals.
   (Pending; Tier B signal code exists as tested building blocks)

Each stage replaces a fake with a real thing behind an interface that does not change. The
frontend's `ApiProvider` interface has fixture and HTTP implementations, chosen at build time
by `VITE_API_URL`; an HTTP build carries neither the fixture provider nor the dataset.

### Three-tier scoring

| Tier | What | Allowed to | State |
|------|------|------------|-------|
| A | Published deterministic scores (NEWS2, GWTG-HF). No training. | Sort the list. Alert. | NEWS2 built; GWTG-HF not |
| B | Mechanism axes: arrhythmic burden, respiratory trajectory, perfusion. Open weights or rules. | Display. Alert. | Signal code built; not in the scoring |
| C | Our own outcome head. Trained off cohort. | Display only. Never sorts, never alerts. | Not built |

Tier A sorts until Tier C beats it on a pre-registered comparison. This is deliberate.

### Cloud mapping (Huawei)

The production column is the plan; none of it is built.

| Concern | Local | Production |
|---------|-------|------------|
| Device ingest | Mosquitto MQTT | IoTDA |
| Gateway compute | Local process | Intelligent EdgeFabric |
| Waveform storage | Filesystem | OBS |
| Derived vitals | InfluxDB | GeminiDB Influx |
| Profile and scores | PostgreSQL | GaussDB |
| Model training | PyTorch | ModelArts |
| Waveform inference | ONNX Runtime | MindSpore Lite on Ascend |
| Scoring trigger | Local scheduler | FunctionGraph |
| REST API | FastAPI | API Gateway |
| Alerting | Log line | SMN |
| Audit trail | File | LTS |
| Access control | Stub identity | IAM |

## Design principles

These are architectural, not stylistic. Violating one is a defect.

**I1. Missing is missing.** Nothing is imputed, interpolated, or defaulted to zero. A missing
value renders as "--", never as a low number.

**I2. Every value carries provenance.** Source (device, nurse, lab), tier, timestamp,
quality. On screen: serif typeface for device values, sans-serif with superscript N for
nurse-entered values.

**I3. Tier separation.** The sort runs on Tier A. Tier C never sorts and never alerts.

**I4. Abstention is an output.** NOT RANKED is a first-class row with a reason and an
instruction. It never looks like a low score.

**I5. No training on BioSentry patients.** All supervised weights transfer from public or
credentialed research corpora. Local data calibrates and validates only.

**I6. Synthetic flag propagates.** Every fixture record is tagged `synthetic: true`. Joined
data is a presentation device, never training data.

**I7. Privacy.** Health data under RA 10173. One screen per clinician, their patients only,
audit on every view.

**I8. Transport.** BLE to gateway, Wi-Fi or 4G to cloud. NB-IoT is excluded by design.

## Design language

Clinical instrument aesthetic. Near-white ground (`#f8f7f5`), near-black ink (`#1a1a1a`).
Source Serif 4 for clinical content, Inter for interface chrome. Zero border radius.
Crosshair corner marks on interactive regions. No shadows, no gradients, no rounded cards.

**No colour in the ranked list.** Rank position carries urgency. Colour invites triage by
hue, which is the failure mode of existing alarm systems.

Full token definitions in `frontend/src/index.css`.

## Tech stack

All dependencies are exact-pinned. No caret ranges, no tilde ranges.

### Frontend (implemented)

| Package | Version | Role |
|---------|---------|------|
| Vite | 8.2.2 | Build tooling |
| React, React DOM | 19.2.8 | UI framework |
| React Router DOM | 7.18.4 | Client-side routing |
| TypeScript | 6.0.3 | Type safety |
| Vitest | 4.1.11 | Tests (dev); jsdom 28.1.0 and Testing Library for interaction tests |

### Backend (implemented)

| Package | Version | Role |
|---------|---------|------|
| Python | 3.11 | Language |
| FastAPI | 0.143.0 | API |
| Pydantic | 2.14.1 | Validation and the contract |
| uvicorn | 0.54.0 | Server |
| NumPy | 2.4.6 | Signal code and the synthetic generator |
| pytest, Hypothesis, ruff, mypy | see `backend/pyproject.toml` | Tests and checks (dev) |

`contracts/` is a separate npm package (openapi-typescript 7.13.0) because it peers on
TypeScript 5 while `frontend/` is on 6.

### Planned, not built

SQLAlchemy 2 and Alembic, PostgreSQL 16, InfluxDB 2.x, Mosquitto, SciPy, NeuroKit2, LightGBM,
scikit-learn, ONNX Runtime.

## Build status

| Part | State |
|------|-------|
| Design tokens, ward row specification | Done |
| Frontend: four screens, fixture and HTTP providers, vitals entry | Done |
| Contract: schemas, OpenAPI, generated types, drift check in CI | Done |
| API: ranked ward, patient detail, notes, labs, admission, nurse-recorded vitals, audit, scoping | Done, on synthetic data, in memory |
| Tier A: NEWS2 and the escalation arbiter (rules 1 and 5; the others are inert hooks) | Done |
| Snapshot cache, launcher, `make dev`, CI gate | Done |
| Tier B signal code: R peaks, HRV, burden, baseline, respiratory rate, perfusion index | Built and tested; not wired into scoring |
| Tier B and C in the scoring; trained models; any evaluation on real data | Pending |
| Sensor replay, quality gate, gateway; database; real authentication; document extraction | Pending |
