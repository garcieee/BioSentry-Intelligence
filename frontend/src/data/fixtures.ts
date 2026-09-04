// Typed fixture data for the twelve reference patients.
// Every value carries provenance (I2). Every record is synthetic (I6).
// Replaced by an API fetch client in prompt 04.

import type {
  AbstainedRow,
  AdmitPatientInput,
  ClinicalNote,
  LabExtractionResult,
  LabPanel,
  Measurement,
  PartialLabInput,
  PatientDetail,
  PatientExtractionResult,
  Provenance,
  ScoreRow,
  TierCAttribution,
  TierCData,
  TierStatus,
  VitalHistory,
  Vitals,
  WardResponse,
} from "../types";

// --- Provenance helpers ---

const deviceProv = (observed_at: string): Provenance => ({
  source: "device",
  tier: null,
  observed_at,
  computed_at: null,
  model_id: null,
  synthetic: true,
  quality: "ok",
});

const nurseProv = (observed_at: string): Provenance => ({
  source: "nurse",
  tier: null,
  observed_at,
  computed_at: null,
  model_id: null,
  synthetic: true,
  quality: "ok",
});

const labProv = (observed_at: string): Provenance => ({
  source: "lab",
  tier: null,
  observed_at,
  computed_at: null,
  model_id: null,
  synthetic: true,
  quality: "ok",
});

function present<T>(value: T, prov: Provenance): Measurement<T> {
  return { data: { present: true, value }, provenance: prov };
}

function missing<T>(reason: string, prov: Provenance): Measurement<T> {
  return { data: { present: false, reason }, provenance: prov };
}

const TIERS: TierStatus[] = [
  { tier: "A", live: true, label: "NEWS2" },
  { tier: "B", live: true, label: "Mechanism axes" },
  { tier: "C", live: true, label: "Outcome model" },
];

const now = "2026-09-03T07:00:00Z";

// --- Sparkline generators ---

function genTrend(base: number, variance: number, direction: number, n = 12): number[] {
  const out: number[] = [];
  let v = base - direction * variance * 0.5;
  for (let i = 0; i < n; i++) {
    v += direction * (variance / n) + (Math.sin(i * 1.3) * variance * 0.15);
    out.push(Math.round(v * 10) / 10);
  }
  return out;
}

function genHistory(base: number, variance: number, direction: number, n = 24): VitalHistory[] {
  const values = genTrend(base, variance, direction, n);
  return values.map((v, i) => ({
    time: `${String(Math.floor((i / n) * 6)).padStart(2, "0")}:${String(Math.floor(((i / n) * 6 % 1) * 60)).padStart(2, "0")}`,
    value: v,
  }));
}

// --- Vitals builders ---

function makeVitals(
  hr: number, rr: number, spo2: number, temp: number,
  bp: string | null, avpu: string | null,
  ts: string, nurseTs: string,
): Vitals {
  return {
    heart_rate: present(hr, deviceProv(ts)),
    respiratory_rate: present(rr, deviceProv(ts)),
    spo2: present(spo2, deviceProv(ts)),
    temperature: present(temp, deviceProv(ts)),
    blood_pressure: bp !== null
      ? present(bp, nurseProv(nurseTs))
      : missing("not_measured", nurseProv(nurseTs)),
    consciousness: avpu !== null
      ? present(avpu, nurseProv(nurseTs))
      : missing("not_measured", nurseProv(nurseTs)),
  };
}

function makeLabs(
  freshness: number,
  vals: {
    troponin?: number; ck_mb?: number; bnp?: number; nt_probnp?: number;
    sodium?: number; potassium?: number; chloride?: number;
    magnesium?: number; calcium?: number;
    creatinine?: number; bun?: number;
    hemoglobin?: number; hematocrit?: number; wbc?: number; platelet_count?: number;
    pt?: number; inr?: number;
    sgpt?: number; sgot?: number;
    blood_glucose?: number; lactate?: number;
  },
): LabPanel {
  const labTs = new Date(
    new Date(now).getTime() - freshness * 3600_000,
  ).toISOString();
  const p = labProv(labTs);
  const m = (v: number | undefined) => v !== undefined ? present(v, p) : null;
  return {
    troponin: m(vals.troponin),
    ck_mb: m(vals.ck_mb),
    bnp: m(vals.bnp),
    nt_probnp: m(vals.nt_probnp),
    sodium: m(vals.sodium),
    potassium: m(vals.potassium),
    chloride: m(vals.chloride),
    magnesium: m(vals.magnesium),
    calcium: m(vals.calcium),
    creatinine: m(vals.creatinine),
    bun: m(vals.bun),
    hemoglobin: m(vals.hemoglobin),
    hematocrit: m(vals.hematocrit),
    wbc: m(vals.wbc),
    platelet_count: m(vals.platelet_count),
    pt: m(vals.pt),
    inr: m(vals.inr),
    sgpt: m(vals.sgpt),
    sgot: m(vals.sgot),
    blood_glucose: m(vals.blood_glucose),
    lactate: m(vals.lactate),
    freshness_hours: freshness,
  };
}

// --- Tier C outcome-model fixtures ---
// Calibrated deterioration probability plus signed feature attributions.
// scored_seconds_ago is the model's own inference clock -- it re-scores every
// ~5-15 min, deliberately separate from last_update_s on the vitals feed so the
// probability never reads as live as the device vitals next to it.

const FORECAST_WINDOW = "next 1–4h";

function makeTierC(
  risk_probability: number,
  scored_seconds_ago: number,
  attributions: TierCAttribution[],
): TierCData {
  return {
    risk_probability,
    forecast_window: FORECAST_WINDOW,
    scored_seconds_ago,
    attributions,
  };
}

// --- The twelve patients ---

const ranked: ScoreRow[] = [
  {
    id: "p-001", rank: 1, score: 9, trend: "rising",
    name: "Santos, Maria", age: 67, sex: "F", bed: "4A",
    admitting_context: "Acute decompensated heart failure, admitted 36h ago",
    mechanism: "Sorted on NEWS2. Tier B and C pending implementation.",
    supporting: "HR 118 bpm, BP 88/52 (nurse), BNP 1840 pg/mL (lab, 1h)",
    vitals: makeVitals(118, 26, 91, 37.2, "88/52", "A", now, now),
    vital_trends: {
      heart_rate: genTrend(102, 20, 1),
      respiratory_rate: genTrend(20, 8, 1),
      spo2: genTrend(94, 4, -1),
      temperature: genTrend(37.0, 0.4, 0.5),
    },
    labs: makeLabs(1, { bnp: 1840, sodium: 133, potassium: 3.8, creatinine: 1.4, bun: 28, hemoglobin: 118, wbc: 11.2, platelet_count: 198000, sgpt: 42, blood_glucose: 126 }),
    sort_tier: "A",
    tier_status: TIERS,
    tier_b: { arrhythmia_burden: 0.12, respiratory_rate_baseline: 16, perfusion_index: 0.3, substrate_risk: "K+ within range, renal clearance declining" },
    tier_c: makeTierC(0.23, 420, [
      { feature: "Respiratory rate vs baseline", contribution: 0.31 },
      { feature: "BNP (last lab)", contribution: 0.18 },
      { feature: "Pulse pressure narrowing", contribution: 0.14 },
      { feature: "SpO₂ trend slope (3h)", contribution: 0.09 },
      { feature: "Heart rate trend slope (3h)", contribution: 0.05 },
      { feature: "Diuretic response (6h)", contribution: -0.06 },
    ]),
    synthetic: true, signal_quality: 94, last_update_s: 4,
  },
  {
    id: "p-002", rank: 2, score: 7, trend: "stable",
    name: "Reyes, Carlos", age: 54, sex: "M", bed: "2B",
    admitting_context: "Post-ACS step-down, 6h since transfer from CCU, on metoprolol",
    mechanism: "Sorted on NEWS2. Tier B and C pending implementation.",
    supporting: "HR 58 bpm, BP 104/68 (nurse), Troponin 0.42 ng/mL (lab, 3h)",
    vitals: makeVitals(58, 22, 94, 36.8, "104/68", "A", now, now),
    vital_trends: {
      heart_rate: genTrend(62, 8, -0.5),
      respiratory_rate: genTrend(20, 4, 0.3),
      spo2: genTrend(95, 2, -0.2),
      temperature: genTrend(36.8, 0.2, 0),
    },
    labs: makeLabs(3, { troponin: 0.42, ck_mb: 38, sodium: 139, potassium: 4.1, creatinine: 1.0, bun: 16, hemoglobin: 148, wbc: 8.4, platelet_count: 220000, inr: 1.0, blood_glucose: 98 }),
    sort_tier: "A",
    tier_status: TIERS,
    tier_b: { arrhythmia_burden: 0.04, respiratory_rate_baseline: 18, perfusion_index: 0.6, substrate_risk: "troponin trend pending" },
    tier_c: makeTierC(0.12, 300, [
      { feature: "Troponin (last lab)", contribution: 0.16 },
      { feature: "Beta-blocker on board", contribution: -0.14 },
      { feature: "Age", contribution: 0.05 },
      { feature: "Heart rate variability (SDNN)", contribution: 0.04 },
      { feature: "Respiratory rate vs baseline", contribution: 0.03 },
      { feature: "SpO₂ trend slope (3h)", contribution: -0.02 },
    ]),
    synthetic: true, signal_quality: 98, last_update_s: 2,
  },
  {
    id: "p-003", rank: 3, score: 5, trend: "falling",
    name: "Villanueva, Jose", age: 45, sex: "M", bed: "1C",
    admitting_context: "Post-operative day 1, CABG, stable",
    mechanism: "Sorted on NEWS2. Tier B and C pending implementation.",
    supporting: "HR 82 bpm, BP 126/78 (nurse), Hgb 10.2 g/dL (lab, 4h)",
    vitals: makeVitals(82, 18, 96, 37.4, "126/78", "A", now, now),
    vital_trends: {
      heart_rate: genTrend(90, 12, -1),
      respiratory_rate: genTrend(20, 4, -0.5),
      spo2: genTrend(95, 2, 0.5),
      temperature: genTrend(37.6, 0.4, -0.5),
    },
    labs: makeLabs(4, { sodium: 140, potassium: 4.3, creatinine: 0.9, bun: 14, hemoglobin: 102, hematocrit: 0.31, wbc: 9.8, platelet_count: 245000, pt: 12.1, inr: 1.1, blood_glucose: 110 }),
    sort_tier: "A",
    tier_status: TIERS,
    tier_b: { arrhythmia_burden: 0.01, respiratory_rate_baseline: 17, perfusion_index: 0.7, substrate_risk: "normal" },
    tier_c: makeTierC(0.08, 540, [
      { feature: "Post-op day 1", contribution: 0.11 },
      { feature: "Hemoglobin (last lab)", contribution: 0.07 },
      { feature: "Temperature trend (6h)", contribution: -0.05 },
      { feature: "Heart rate trend slope (3h)", contribution: -0.04 },
      { feature: "Respiratory rate vs baseline", contribution: 0.02 },
    ]),
    synthetic: true, signal_quality: 96, last_update_s: 8,
  },
  {
    id: "p-006", rank: 4, score: 5, trend: "stable",
    name: "Bautista, Elena", age: 72, sex: "F", bed: "3A",
    admitting_context: "Heart failure with reduced EF, chronic, admitted for volume overload",
    mechanism: "Sorted on NEWS2. Tier B and C pending implementation.",
    supporting: "HR 94 bpm, BP 110/70 (nurse), BNP 920 pg/mL (lab, 9h)",
    vitals: makeVitals(94, 20, 95, 36.9, "110/70", "A", now, now),
    vital_trends: {
      heart_rate: genTrend(92, 6, 0.2),
      respiratory_rate: genTrend(19, 3, 0.1),
      spo2: genTrend(95, 1.5, 0),
      temperature: genTrend(36.9, 0.2, 0),
    },
    labs: makeLabs(9, { bnp: 920, sodium: 131, potassium: 4.6, creatinine: 1.8, bun: 32, hemoglobin: 110, wbc: 7.6, platelet_count: 175000, sgpt: 38, blood_glucose: 118 }),
    sort_tier: "A",
    tier_status: TIERS,
    tier_b: { arrhythmia_burden: 0.08, respiratory_rate_baseline: 18, perfusion_index: 0.45, substrate_risk: "creatinine rising, labs stale" },
    tier_c: makeTierC(0.14, 660, [
      { feature: "Creatinine trend", contribution: 0.13 },
      { feature: "BNP (last lab)", contribution: 0.10 },
      { feature: "Sodium (last lab)", contribution: 0.08 },
      { feature: "Perfusion index", contribution: 0.06 },
      { feature: "Respiratory rate vs baseline", contribution: 0.04 },
      { feature: "Labs stale (>8h)", contribution: 0.03 },
    ]),
    synthetic: true, signal_quality: 91, last_update_s: 6,
  },
  {
    id: "p-007", rank: 5, score: 4, trend: "stable",
    name: "Garcia, Roberto", age: 61, sex: "M", bed: "5B",
    admitting_context: "Heart failure, suspected, no echocardiogram yet",
    mechanism: "Sorted on NEWS2. Tier B and C pending implementation.",
    supporting: "HR 88 bpm, BP 132/84 (nurse), BNP not measured",
    vitals: makeVitals(88, 20, 96, 37.0, "132/84", "A", now, now),
    vital_trends: {
      heart_rate: genTrend(86, 6, 0.3),
      respiratory_rate: genTrend(19, 3, 0.1),
      spo2: genTrend(96, 1, 0),
      temperature: genTrend(37.0, 0.1, 0),
    },
    labs: makeLabs(5, { sodium: 138, potassium: 4.0, creatinine: 1.1, bun: 18, hemoglobin: 142, wbc: 6.8, platelet_count: 230000, blood_glucose: 105 }),
    sort_tier: "A",
    tier_status: TIERS,
    tier_b: { arrhythmia_burden: 0.02, respiratory_rate_baseline: null, perfusion_index: 0.6, substrate_risk: "incomplete workup" },
    tier_c: makeTierC(0.09, 480, [
      { feature: "Incomplete workup (no echo)", contribution: 0.08 },
      { feature: "Blood pressure", contribution: 0.05 },
      { feature: "Heart rate trend slope (3h)", contribution: 0.04 },
      { feature: "Respiratory rate vs baseline", contribution: 0.03 },
      { feature: "Age", contribution: 0.03 },
    ]),
    synthetic: true, signal_quality: 97, last_update_s: 3,
  },
  {
    id: "p-008", rank: 6, score: 3, trend: "stable",
    name: "Mendoza, Ana", age: 55, sex: "F", bed: "6A",
    admitting_context: "Hypertensive urgency, responding to IV labetalol",
    mechanism: "Sorted on NEWS2. Tier B and C pending implementation.",
    supporting: "HR 76 bpm, BP 158/96 (nurse)",
    vitals: makeVitals(76, 16, 98, 36.7, "158/96", "A", now, now),
    vital_trends: {
      heart_rate: genTrend(80, 8, -0.5),
      respiratory_rate: genTrend(17, 2, -0.2),
      spo2: genTrend(98, 0.5, 0),
      temperature: genTrend(36.7, 0.1, 0),
    },
    labs: makeLabs(2, { sodium: 142, potassium: 3.9, creatinine: 0.9, bun: 12, hemoglobin: 132, wbc: 7.2, platelet_count: 260000, sgpt: 28, blood_glucose: 92 }),
    sort_tier: "A",
    tier_status: TIERS,
    tier_b: { arrhythmia_burden: 0.01, respiratory_rate_baseline: 16, perfusion_index: 0.8, substrate_risk: "normal" },
    tier_c: makeTierC(0.05, 360, [
      { feature: "Systolic blood pressure", contribution: 0.07 },
      { feature: "Labetalol response", contribution: -0.06 },
      { feature: "Heart rate trend slope (3h)", contribution: -0.03 },
      { feature: "SpO₂ (current)", contribution: -0.02 },
      { feature: "Age", contribution: 0.02 },
    ]),
    synthetic: true, signal_quality: 99, last_update_s: 1,
  },
  {
    id: "p-009", rank: 7, score: 2, trend: "falling",
    name: "Cruz, Patricia", age: 38, sex: "F", bed: "7B",
    admitting_context: "Atrial fibrillation, rate controlled, awaiting cardioversion",
    mechanism: "Sorted on NEWS2. Tier B and C pending implementation.",
    supporting: "HR 84 bpm, BP 122/76 (nurse)",
    vitals: makeVitals(84, 14, 98, 36.6, "122/76", "A", now, now),
    vital_trends: {
      heart_rate: genTrend(88, 8, -0.5),
      respiratory_rate: genTrend(15, 2, -0.2),
      spo2: genTrend(98, 0.5, 0.1),
      temperature: genTrend(36.6, 0.1, 0),
    },
    labs: makeLabs(6, { sodium: 140, potassium: 4.2, creatinine: 0.8, bun: 15, hemoglobin: 128, wbc: 6.0, platelet_count: 210000, blood_glucose: 88 }),
    sort_tier: "A",
    tier_status: TIERS,
    tier_b: { arrhythmia_burden: 0.35, respiratory_rate_baseline: 15, perfusion_index: 0.7, substrate_risk: "normal" },
    tier_c: makeTierC(0.06, 600, [
      { feature: "Arrhythmia burden", contribution: 0.09 },
      { feature: "Rate control (6h)", contribution: -0.05 },
      { feature: "Age", contribution: -0.03 },
      { feature: "Respiratory rate vs baseline", contribution: -0.02 },
      { feature: "SpO₂ trend slope (3h)", contribution: -0.02 },
    ]),
    synthetic: true, signal_quality: 95, last_update_s: 5,
  },
  {
    id: "p-010", rank: 8, score: 2, trend: "stable",
    name: "Aquino, Daniel", age: 29, sex: "M", bed: "8A",
    admitting_context: "Chest pain, low risk, admitted 4h ago for observation",
    mechanism: "Sorted on NEWS2. Tier B and C pending implementation.",
    supporting: "HR 72 bpm, BP 120/78 (nurse), Troponin <0.01 ng/mL (lab, 2h)",
    vitals: makeVitals(72, 14, 99, 36.5, "120/78", "A", now, now),
    vital_trends: {
      heart_rate: genTrend(72, 4, 0),
      respiratory_rate: genTrend(14, 1, 0),
      spo2: genTrend(99, 0.3, 0),
      temperature: genTrend(36.5, 0.1, 0),
    },
    labs: makeLabs(2, { troponin: 0.009, sodium: 141, potassium: 4.0, creatinine: 0.9, bun: 13, hemoglobin: 155, wbc: 7.0, platelet_count: 280000, blood_glucose: 94 }),
    sort_tier: "A",
    tier_status: TIERS,
    tier_b: { arrhythmia_burden: 0.0, respiratory_rate_baseline: null, perfusion_index: 0.9, substrate_risk: "normal" },
    tier_c: makeTierC(0.03, 300, [
      { feature: "Troponin negative (last lab)", contribution: -0.06 },
      { feature: "Age", contribution: -0.05 },
      { feature: "Heart rate trend slope (3h)", contribution: 0.02 },
      { feature: "Respiratory rate vs baseline", contribution: 0.01 },
      { feature: "SpO₂ (current)", contribution: -0.01 },
    ]),
    synthetic: true, signal_quality: 99, last_update_s: 2,
  },
  {
    id: "p-011", rank: 9, score: 1, trend: "stable",
    name: "Tan, Lucinda", age: 68, sex: "F", bed: "9A",
    admitting_context: "Chronic stable angina, medication adjustment",
    mechanism: "Sorted on NEWS2. Tier B and C pending implementation.",
    supporting: "HR 70 bpm, BP 134/82 (nurse)",
    vitals: makeVitals(70, 15, 97, 36.4, "134/82", "A", now, now),
    vital_trends: {
      heart_rate: genTrend(71, 3, 0),
      respiratory_rate: genTrend(15, 1, 0),
      spo2: genTrend(97, 0.5, 0),
      temperature: genTrend(36.4, 0.1, 0),
    },
    labs: makeLabs(7, { sodium: 139, potassium: 4.4, creatinine: 1.0, bun: 17, hemoglobin: 126, wbc: 6.5, platelet_count: 195000, blood_glucose: 100 }),
    sort_tier: "A",
    tier_status: TIERS,
    tier_b: { arrhythmia_burden: 0.01, respiratory_rate_baseline: 15, perfusion_index: 0.85, substrate_risk: "normal" },
    tier_c: makeTierC(0.04, 4200, [
      { feature: "Age", contribution: 0.05 },
      { feature: "Chronic angina history", contribution: 0.04 },
      { feature: "Heart rate trend slope (3h)", contribution: -0.02 },
      { feature: "Respiratory rate vs baseline", contribution: 0.01 },
      { feature: "SpO₂ trend slope (3h)", contribution: -0.01 },
    ]),
    synthetic: true, signal_quality: 97, last_update_s: 7,
  },
  {
    id: "p-012", rank: 10, score: 0, trend: "stable",
    name: "Lim, Francis", age: 42, sex: "M", bed: "10B",
    admitting_context: "Pericarditis, improving, discharge planned tomorrow",
    mechanism: "Sorted on NEWS2. Tier B and C pending implementation.",
    supporting: "HR 68 bpm, BP 118/72 (nurse)",
    vitals: makeVitals(68, 13, 99, 36.5, "118/72", "A", now, now),
    vital_trends: {
      heart_rate: genTrend(70, 4, -0.3),
      respiratory_rate: genTrend(14, 1, -0.1),
      spo2: genTrend(99, 0.3, 0),
      temperature: genTrend(36.5, 0.1, -0.1),
    },
    labs: makeLabs(3, { sodium: 140, potassium: 4.1, creatinine: 0.8, bun: 11, hemoglobin: 150, wbc: 5.8, platelet_count: 240000, blood_glucose: 90 }),
    sort_tier: "A",
    tier_status: TIERS,
    tier_b: { arrhythmia_burden: 0.0, respiratory_rate_baseline: 14, perfusion_index: 0.9, substrate_risk: "normal" },
    tier_c: makeTierC(0.02, 5400, [
      { feature: "Improving trajectory (24h)", contribution: -0.07 },
      { feature: "Age", contribution: -0.04 },
      { feature: "Heart rate trend slope (3h)", contribution: -0.03 },
      { feature: "Temperature trend (6h)", contribution: -0.02 },
      { feature: "Respiratory rate vs baseline", contribution: -0.01 },
    ]),
    synthetic: true, signal_quality: 98, last_update_s: 3,
  },
];

// --- Abstained patients ---

const abstained: AbstainedRow[] = [
  {
    id: "p-004", name: "Flores, Ramon", age: 73, sex: "M", bed: "4B",
    admitting_context: "Heart failure with preserved EF, admitted 2h ago",
    reason: "Blood pressure not recorded",
    instruction: "Record blood pressure to enable scoring",
    synthetic: true,
  },
  {
    id: "p-005", name: "de Leon, Isabel", age: 58, sex: "F", bed: "3B",
    admitting_context: "Congestive heart failure, diuretic titration",
    reason: "Signal usable 22% of last hour",
    instruction: "Check patch adhesion",
    synthetic: true,
  },
];

// --- Clinician-to-patient assignments (fixture-only, replaced by server auth in production) ---

const CLINICIAN_PATIENTS: Record<string, string[]> = {
  "rn-delacruz": ["p-001", "p-002", "p-004", "p-006", "p-009", "p-012"],
  "rn-reyes":    ["p-003", "p-005", "p-007", "p-008", "p-010", "p-011"],
  "md-santos":   ["p-001", "p-002", "p-006", "p-008", "p-011"],
  "md-aquino":   ["p-003", "p-007", "p-009", "p-010", "p-012"],
  "rn-manalo":   ["p-001", "p-002", "p-003", "p-004", "p-005", "p-006",
                  "p-007", "p-008", "p-009", "p-010", "p-011", "p-012"],
};

let _activeClinician: string | null = null;

export function setActiveClinician(id: string | null): void {
  _activeClinician = id;
}

function visiblePatientIds(): Set<string> | null {
  if (!_activeClinician) return null;
  const ids = CLINICIAN_PATIENTS[_activeClinician];
  if (!ids) return null;
  return new Set(ids);
}

// --- Ward response ---

export async function getWard(): Promise<WardResponse> {
  const allowed = visiblePatientIds();
  const filteredRanked = allowed
    ? ranked.filter((r) => allowed.has(r.id))
    : ranked;
  const filteredAbstained = allowed
    ? abstained.filter((a) => allowed.has(a.id))
    : abstained;

  // Re-rank after filtering so ranks are contiguous
  const reRanked = filteredRanked.map((r, i) => ({ ...r, rank: i + 1 }));

  return {
    ward: "W4",
    clinician: _activeClinician ?? "unknown",
    shift: "07:00",
    receiving_data: true,
    sort_tier: "A",
    tier_status: TIERS,
    ranked: reRanked,
    abstained: filteredAbstained,
  };
}

// --- Clinical notes (in-memory, replaced by API in prompt 04) ---

const notesStore: Map<string, ClinicalNote[]> = new Map([
  ["p-001", [
    { id: "n-001", patient_id: "p-001", author: "RN Dela Cruz", role: "RN", timestamp: "2026-09-03T06:45:00Z", content: "Patient restless, diaphoretic. BP trending down from previous shift. Elevated troponin noted -- MD notified." },
    { id: "n-002", patient_id: "p-001", author: "Dr Reyes", role: "MD", timestamp: "2026-09-03T06:30:00Z", content: "Reviewed labs. Troponin rise consistent with NSTEMI. Cardiology consult placed. Hold metoprolol if SBP < 100." },
  ]],
  ["p-002", [
    { id: "n-003", patient_id: "p-002", author: "RN Santos", role: "RN", timestamp: "2026-09-03T06:15:00Z", content: "Increased work of breathing. Repositioned to high Fowler's. SpO2 improved from 91% to 93% on 4L NC." },
  ]],
  ["p-003", [
    { id: "n-004", patient_id: "p-003", author: "RN Dela Cruz", role: "RN", timestamp: "2026-09-03T05:50:00Z", content: "Patient alert and oriented. Tolerating oral meds. No acute complaints this shift." },
  ]],
]);

export async function getNotes(patientId: string): Promise<ClinicalNote[]> {
  return notesStore.get(patientId) ?? [];
}

export async function addNote(patientId: string, author: string, role: string, content: string): Promise<ClinicalNote> {
  const note: ClinicalNote = {
    id: `n-${Date.now()}`,
    patient_id: patientId,
    author,
    role,
    timestamp: new Date().toISOString(),
    content,
  };
  const existing = notesStore.get(patientId) ?? [];
  notesStore.set(patientId, [note, ...existing]);
  return note;
}

export async function deleteNote(patientId: string, noteId: string): Promise<void> {
  const existing = notesStore.get(patientId) ?? [];
  notesStore.set(patientId, existing.filter((n) => n.id !== noteId));
}

// --- Admin functions (STUB: replaced by API calls in prompt 04) ---

function nextPatientId(): string {
  const all = [...ranked, ...abstained];
  const nums = all.map((p) => parseInt(p.id.replace("p-", ""), 10)).filter((n) => !isNaN(n));
  const next = Math.max(0, ...nums) + 1;
  return `p-${String(next).padStart(3, "0")}`;
}

export async function admitPatient(input: AdmitPatientInput): Promise<AbstainedRow> {
  const id = nextPatientId();
  const row: AbstainedRow = {
    id,
    name: `${input.lastName}, ${input.firstName}`,
    age: input.age,
    sex: input.sex,
    bed: input.bed,
    admitting_context: input.admittingContext,
    reason: "Patch not yet applied",
    instruction: "Apply chest patch and verify signal",
    synthetic: true,
  };
  abstained.push(row);
  return row;
}

export async function enterLabResults(
  patientId: string,
  labs: PartialLabInput,
): Promise<LabPanel> {
  const ts = new Date().toISOString();
  const prov = labProv(ts);
  const idx = ranked.findIndex((r) => r.id === patientId);
  if (idx === -1) throw new Error(`Patient ${patientId} not found in ranked list`);

  const existing = ranked[idx].labs;
  const u = (key: keyof PartialLabInput) =>
    labs[key] !== undefined ? present(labs[key], prov) : existing[key];
  const updated: LabPanel = {
    troponin: u("troponin"), ck_mb: u("ck_mb"), bnp: u("bnp"), nt_probnp: u("nt_probnp"),
    sodium: u("sodium"), potassium: u("potassium"), chloride: u("chloride"),
    magnesium: u("magnesium"), calcium: u("calcium"),
    creatinine: u("creatinine"), bun: u("bun"),
    hemoglobin: u("hemoglobin"), hematocrit: u("hematocrit"),
    wbc: u("wbc"), platelet_count: u("platelet_count"),
    pt: u("pt"), inr: u("inr"),
    sgpt: u("sgpt"), sgot: u("sgot"),
    blood_glucose: u("blood_glucose"), lactate: u("lactate"),
    freshness_hours: 0,
  };
  ranked[idx] = { ...ranked[idx], labs: updated } as ScoreRow;
  return updated;
}

// --- Document extraction (STUB: replaced by OCR pipeline in prompt 04) ---

export async function extractLabsFromFile(
  _file: File,
): Promise<LabExtractionResult> {
  await new Promise((r) => setTimeout(r, 2000));
  return {
    values: { troponin: 0.08, sodium: 138, potassium: 4.1, creatinine: 1.2, hemoglobin: 140, blood_glucose: 102 },
    confidence: { troponin: 0.92, sodium: 0.95, potassium: 0.97, creatinine: 0.88, hemoglobin: 0.94, blood_glucose: 0.91 },
    synthetic: true,
    model_id: "stub-ocr-v0",
  };
}

export async function extractPatientFromFile(
  _file: File,
): Promise<PatientExtractionResult> {
  await new Promise((r) => setTimeout(r, 2000));
  return {
    values: {
      lastName: "Dela Cruz",
      firstName: "Juan",
      age: 55,
      sex: "M",
      dateOfBirth: "1971-03-14",
      chiefComplaint: "Chest pain, onset 2 hours ago",
      admittingContext: "Chest pain, rule out ACS",
    },
    confidence: {
      lastName: 0.95,
      firstName: 0.95,
      age: 0.88,
      sex: 0.99,
      dateOfBirth: 0.90,
      chiefComplaint: 0.82,
      admittingContext: 0.78,
    },
    synthetic: true,
    model_id: "stub-ocr-v0",
  };
}

// --- Patient lookup ---

export async function listAllPatients(): Promise<Array<{ id: string; name: string; bed: string; ranked: boolean }>> {
  const allowed = visiblePatientIds();
  const r = allowed ? ranked.filter((p) => allowed.has(p.id)) : ranked;
  const a = allowed ? abstained.filter((p) => allowed.has(p.id)) : abstained;
  return [
    ...r.map((p) => ({ id: p.id, name: p.name, bed: p.bed, ranked: true })),
    ...a.map((p) => ({ id: p.id, name: p.name, bed: p.bed, ranked: false })),
  ];
}

export async function getPatient(id: string): Promise<PatientDetail | null> {
  const allowed = visiblePatientIds();
  if (allowed && !allowed.has(id)) return null;
  const row = ranked.find((r) => r.id === id);
  if (!row) return null;
  return {
    ...row,
    vital_history: {
      heart_rate: genHistory(
        row.vitals.heart_rate.data.present ? row.vitals.heart_rate.data.value : 70,
        15, row.trend === "rising" ? 1 : row.trend === "falling" ? -1 : 0,
      ),
      respiratory_rate: genHistory(
        row.vitals.respiratory_rate.data.present ? row.vitals.respiratory_rate.data.value : 16,
        5, row.trend === "rising" ? 0.5 : 0,
      ),
      spo2: genHistory(
        row.vitals.spo2.data.present ? row.vitals.spo2.data.value : 97,
        3, row.trend === "rising" ? -0.5 : 0.2,
      ),
    },
    tier_breakdown: {
      tier_a: { score: row.score, label: `NEWS2 = ${row.score}` },
      tier_b: row.tier_b,
      tier_c: row.tier_c,
    },
  };
}
