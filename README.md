# BioSentry

Continuous cardiovascular deterioration **ranking** for general hospital wards in the Philippines.

BioSentry answers one question: *of your twenty patients, see this one first.* An adhesive chest patch worn three to five days produces continuous signal. The hospital supplies the rest: admitting diagnosis, ejection fraction, comorbidities, medications, labs, and two nurse-entered values (blood pressure and level of consciousness). Both halves land on one patient row, in one ranked list, on one screen per clinician.

**This is not a diagnosis system.** It ranks and displays. A human decides.

---

## Quick start

### Prerequisites

| Tool | Version | Why |
|------|---------|-----|
| Node.js | 20+ | Frontend build tooling |
| npm | 9+ | Package management |
| Git | any | Version control |
| Make | any | Task runner |

### Run the dashboard

```bash
git clone <repo-url> && cd Huawei-Innovation-Winners

# Install dependencies
make web-install

# Start the development server
make web-dev
```

Open [http://localhost:5173](http://localhost:5173). Select a department, pick a clinician profile, and sign in.

### Makefile commands

| Command | What it does |
|---------|-------------|
| `make web-install` | Install frontend dependencies (`npm ci`) |
| `make web-dev` | Start Vite dev server with hot reload |
| `make web-build` | Production build (typecheck + bundle) |
| `make web-typecheck` | Run TypeScript compiler in check mode |
| `make check` | Run all checks (currently: typecheck) |

---

## What you will see

### Sign-in

A four-step flow: department (Nursing or Medical), clinician profile, passphrase, and destination (Ward or Station). Five profiles are available, each assigned to specific patients. This pilot build accepts any passphrase. Live deployments authenticate through the hospital's identity provider.

### Ward view

The core screen. A ranked list of patients ordered by deterioration score, highest first.

- **Status bar** -- ward, operator, shift, and a live indicator showing seconds since last data update
- **Summary cards** -- patients ranked, not ranked, trending up, active scoring tiers, and pending tiers
- **Ranked rows** -- each row shows rank, NEWS2 score, trend direction, patient identity, admitting context, driving mechanism, vitals (with provenance), lab freshness, and which tier the sort ran on
- **Not ranked section** -- patients the system cannot score, each with a reason and an actionable instruction (e.g. "Record blood pressure to enable scoring")

### Patient detail

Click any ranked row. Two-column layout: identity and tier breakdown on the left, vitals and labs on the right. Every value shows its provenance source (device, nurse, lab) so a clinician can tell a device-derived number from a nurse-typed one at a glance. Collapsible panels for Tier A (NEWS2 with sparkline), Tier B (mechanism axes), and Tier C (outcome model). Slide-over drawers for clinical notes and vital trend charts.

### Station

Nurse workstation with three tabs:

- **Admit patient** -- DOH/PhilHealth-aligned admission form (identity, admission details, initial assessment)
- **Enter lab results** -- manual entry for 17 lab fields grouped by section (cardiac biomarkers, electrolytes, renal, hematology, coagulation, liver, metabolic), all in Philippine-standard units
- **Upload** -- document upload with simulated OCR extraction for lab results or patient records, with a review-and-confirm step before saving

---

## Project structure

```
Huawei-Innovation-Winners/
  CLAUDE.md                       Standing context and invariants
  Makefile                        Task runner
  README.md                       This file

  prompts/                        Build prompts, executed in order
    01_DESIGN_AND_ROW.md          Design language and the ward row specification
    02_FRONTEND.md                React frontend on typed fixtures
    03_CONTRACT.md                Freeze API contract, generate types (pending)
    04_BACKEND.md                 Python backend (pending)
    05_PIPELINE.md                Real pipeline (pending)

  docs/
    ph-clinical-standards.md      Philippine admission, lab, and regulatory reference

  backend/                        Python backend (pending)
  models/                         Trained model artifacts (pending)

  frontend/                       React frontend (Vite + TypeScript)
    package.json
    index.html
    src/
      main.tsx                    App bootstrap with React Router
      App.tsx                     Route definitions and session state
      index.css                   Design tokens and global styles
      types/
        index.ts                  All data shapes (hand-written, replaced by generated types in prompt 03)
      data/
        fixtures.ts               10 typed patients with full provenance, clinician-to-patient filtering
      api/
        contract.ts               ApiProvider interface (fixture and HTTP providers)
        client.ts                 Typed fetch wrapper with auth token injection
        index.ts                  Provider selection (fixture vs HTTP based on env)
        providers/
          fixture.ts              Delegates to fixtures.ts for local development
          http.ts                 Real HTTP calls to backend API
      components/
        WardRow.tsx               Ranked patient row (dense grid layout)
        AbstainedRow.tsx          Not-ranked patient row
        MeasurementDisplay.tsx    Renders a value with provenance cues
        Sparkline.tsx             Inline sparkline for vital trends
        TrendChart.tsx            Time-series chart for vital history
        SessionMenu.tsx           Clinician session display and sign-out
      pages/
        SignIn.tsx                Department, profile selection, and authentication
        Ward.tsx                  Ward list with status bar, summary, ranked + abstained sections
        PatientDetail.tsx         Single patient with tier breakdown, vitals, labs, notes, charts
        Station.tsx               Nurse workstation: admit, lab entry, document upload
```

---

## Architecture

BioSentry follows a **frontend-first** build order. The ward row is the product. Everything upstream exists to fill it. The sequence:

1. **Design language** -- tokens, not adjectives. Exact colours, type scale, spacing. (Done)
2. **Frontend on typed fixtures** -- the real interface running on local data. (Done)
3. **Contract freeze** -- extract JSON schemas from the working UI, generate types. (Pending)
4. **Backend** -- FastAPI serving the contract from fixtures, then real data. (Pending)
5. **Pipeline** -- sensor replay, quality gate, feature extraction, scoring. (Pending)

Each stage replaces a fake with a real thing behind an interface that does not change. The API layer is already scaffolded: an `ApiProvider` interface with fixture and HTTP implementations, switchable via environment variable (`VITE_API_URL`).

### Three-tier scoring

| Tier | What | Allowed to |
|------|------|------------|
| A | Published deterministic scores (NEWS2, GWTG-HF). No training. | Sort the list. Alert. |
| B | Mechanism axes: arrhythmic burden, respiratory trajectory, perfusion. Open weights or rules. | Display. Alert. |
| C | Our own outcome head. Trained off cohort. | Display only. Never sorts, never alerts. |

Tier A sorts until Tier C beats it on a pre-registered comparison. This is deliberate.

### Cloud mapping (Huawei)

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

---

## Design principles

These are architectural, not stylistic. Violating one is a defect.

**I1. Missing is missing.** Nothing is imputed, interpolated, or defaulted to zero. A missing value renders as "--", never as a low number.

**I2. Every value carries provenance.** Source (device, nurse, lab), tier, timestamp, quality. On screen: serif typeface for device values, sans-serif with superscript N for nurse-entered values.

**I3. Tier separation.** The sort runs on Tier A. Tier C never sorts and never alerts.

**I4. Abstention is an output.** NOT RANKED is a first-class row with a reason and an instruction. It never looks like a low score.

**I5. No training on BioSentry patients.** All supervised weights transfer from public or credentialed research corpora. Local data calibrates and validates only.

**I6. Synthetic flag propagates.** Every fixture record is tagged `synthetic: true`. Joined data is a presentation device, never training data.

**I7. Privacy.** Health data under RA 10173. One screen per clinician, their patients only, audit on every view.

**I8. Transport.** BLE to gateway, Wi-Fi or 4G to cloud. NB-IoT is excluded by design.

---

## Design language

Clinical instrument aesthetic. Near-white ground (`#f8f7f5`), near-black ink (`#1a1a1a`). Source Serif 4 for clinical content, Inter for interface chrome. Zero border radius. Crosshair corner marks on interactive regions. No shadows, no gradients, no rounded cards.

**No colour in the ranked list.** Rank position carries urgency. Colour invites triage by hue, which is the failure mode of existing alarm systems.

Full token definitions in `frontend/src/index.css`.

---

## Tech stack

### Frontend (implemented)

| Package | Version | Role |
|---------|---------|------|
| Vite | 8.2.2 | Build tooling |
| React | 19.2.8 | UI framework |
| React DOM | 19.2.8 | DOM rendering |
| React Router DOM | 7.6.3 | Client-side routing |
| TypeScript | 6.0.3 | Type safety |

### Backend (pending)

| Package | Role |
|---------|------|
| Python 3.11 | Language |
| FastAPI + Pydantic v2 | API + validation |
| SQLAlchemy 2 + Alembic | ORM + migrations |
| PostgreSQL 16 | Profile and scores |
| InfluxDB 2.x | Derived vitals time series |
| Mosquitto | MQTT broker (local dev) |
| NumPy, SciPy, NeuroKit2 | Signal processing |
| LightGBM, scikit-learn | Tier C model, calibration |
| ONNX Runtime | Waveform model inference |

All dependencies are exact-pinned. No caret ranges, no tilde ranges.

---

## Build status

| Prompt | Status | What it produces |
|--------|--------|-----------------|
| 01 Design and row | Done | Design tokens, row specification |
| 02 Frontend | Done | `frontend/`, four screens on fixtures, API layer scaffolded |
| 03 Contract | Pending | JSON schemas, OpenAPI, generated types |
| 04 Backend | Pending | Python API, types.py, NEWS2, fixtures source |
| 05 Pipeline | Pending | Sensor replay, quality gate, scoring, smoke test |

---

## Licence

Competition entry for the Huawei ICT Competition Innovation Track. No real patient data exists in this repository.
