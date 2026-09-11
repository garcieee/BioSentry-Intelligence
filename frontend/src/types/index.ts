/**
 * Hand-written types for the BioSentry dashboard.
 * These will be replaced by generated types from contracts/ in prompt 03.
 * Keep all shapes here -- do not scatter through components.
 *
 * Invariants: I1 (missing is missing), I2 (provenance on every value),
 * I3 (tier separation), I4 (abstention is not a score), I6 (synthetic flag).
 */

// --- Provenance ---

export type ProvenanceSource =
  | "device"
  | "nurse"
  | "lab"
  | "derived"
  | "model"
  | "reference";

export type Tier = "A" | "B" | "C";

export type QualityLevel = "ok" | "degraded" | "missing";

export interface Provenance {
  readonly source: ProvenanceSource;
  readonly tier: Tier | null;
  readonly observed_at: string;
  readonly computed_at: string | null;
  readonly model_id: string | null;
  readonly synthetic: boolean;
  readonly quality: QualityLevel;
}

// --- Measurement primitives ---

export type MeasurementValue<T> =
  | { readonly present: true; readonly value: T }
  | { readonly present: false; readonly reason: string };

export interface Measurement<T> {
  readonly data: MeasurementValue<T>;
  readonly provenance: Provenance;
}

// --- Vitals ---

export type Trend = "rising" | "falling" | "stable" | "insufficient";

export interface VitalHistory {
  readonly time: string;
  readonly value: number;
}

export interface Vitals {
  readonly heart_rate: Measurement<number>;
  readonly respiratory_rate: Measurement<number>;
  readonly spo2: Measurement<number>;
  readonly temperature: Measurement<number>;
  readonly blood_pressure: Measurement<string>;
  readonly consciousness: Measurement<string>;
}

export interface VitalTrends {
  readonly heart_rate: number[];
  readonly respiratory_rate: number[];
  readonly spo2: number[];
  readonly temperature: number[];
}

export interface VitalHistoryFull {
  readonly heart_rate: VitalHistory[];
  readonly respiratory_rate: VitalHistory[];
  readonly spo2: VitalHistory[];
}

// --- Lab panel ---
// Units follow Philippine hospital convention (conventional/US-style).
// Hemoglobin in g/L (PH standard), liver enzymes labeled SGPT/SGOT.

export interface LabPanel {
  // Cardiac biomarkers
  readonly troponin: Measurement<number> | null;       // ng/mL (conventional) or ng/L (hs)
  readonly ck_mb: Measurement<number> | null;           // U/L
  readonly bnp: Measurement<number> | null;             // pg/mL
  readonly nt_probnp: Measurement<number> | null;       // pg/mL
  // Electrolytes
  readonly sodium: Measurement<number> | null;          // mEq/L
  readonly potassium: Measurement<number> | null;       // mEq/L
  readonly chloride: Measurement<number> | null;        // mEq/L
  readonly magnesium: Measurement<number> | null;       // mg/dL
  readonly calcium: Measurement<number> | null;         // mg/dL
  // Renal
  readonly creatinine: Measurement<number> | null;      // mg/dL
  readonly bun: Measurement<number> | null;             // mg/dL
  // Hematology
  readonly hemoglobin: Measurement<number> | null;      // g/L (PH convention)
  readonly hematocrit: Measurement<number> | null;      // fraction (0-1)
  readonly wbc: Measurement<number> | null;             // x10^9/L
  readonly platelet_count: Measurement<number> | null;  // /mm^3
  // Coagulation
  readonly pt: Measurement<number> | null;              // seconds
  readonly inr: Measurement<number> | null;             // ratio
  // Liver (PH naming)
  readonly sgpt: Measurement<number> | null;            // U/L (ALT)
  readonly sgot: Measurement<number> | null;            // U/L (AST)
  // Metabolic
  readonly blood_glucose: Measurement<number> | null;   // mg/dL
  readonly lactate: Measurement<number> | null;         // mmol/L
  // Meta
  readonly freshness_hours: number | null;
}

// --- Tier system ---

export interface TierStatus {
  readonly tier: Tier;
  readonly live: boolean;
  readonly label: string;
}

// Tier B finding: a named clinical observation with its own units.
// These are NOT comparable on a shared scale -- each carries its own
// measurement unit, direction, and significance threshold.
export interface TierBFinding {
  readonly id: string;
  readonly label: string;
  readonly value: string;              // pre-formatted with units, e.g. "12%", "KDIGO 2"
  readonly direction: "rising" | "falling" | "stable" | "new" | null;
  readonly source: ProvenanceSource;
  readonly significant: boolean;       // exceeds the finding's own threshold
  readonly detail?: string;            // e.g. "vs personal baseline", "corroborates low perfusion"
}

export interface TierBData {
  readonly findings: readonly TierBFinding[];
}

// --- Tier C: outcome model ---

export interface TierCAttribution {
  readonly feature: string;
  // Signed contribution to the current score (SHAP or equivalent).
  // Positive = risk-increasing, negative = protective.
  readonly contribution: number;
}

export interface TierCData {
  // Isotonic-calibrated deterioration probability (0..1). Never the raw model score.
  readonly risk_probability: number;
  // Pre-registered forecast window. Keep in sync with the scoring pipeline
  // and every other place this window is referenced.
  readonly forecast_window: string;
  // Age of the model's own last inference, in seconds. This is the model's
  // clock, NOT the vitals feed's last_update_s -- the model re-scores on its
  // own cadence (~5-15 min) and must not read as live as the device vitals.
  readonly scored_seconds_ago: number;
  readonly attributions: readonly TierCAttribution[];
}

// --- Escalation arbiter ---
// The arbiter is the only component that changes displayed priority.
// Each reason names the rule that fired and carries a human-readable explanation.

export type EscalationRule =
  | "tier_a_threshold"   // NEWS2 crossed its standard band
  | "tier_c_raise"       // Outcome model raised patient above Tier A position
  | "tier_b_finding"     // A mechanism finding raised the patient
  | "missing_input";     // Required input missing → NOT RANKED

export interface EscalationReason {
  readonly rule: EscalationRule;
  readonly text: string;           // human-readable, e.g. "NEWS2 ≥ 7"
  readonly pathway?: string;       // for tier_b_finding: which mechanism
}

// --- Patient rows ---

export interface ScoreRow {
  readonly id: string;
  readonly rank: number;
  readonly score: number;
  readonly trend: Trend;
  readonly name: string;
  readonly age: number | null;
  readonly sex: string | null;
  readonly bed: string;
  readonly admitting_context: string;
  readonly mechanism: string;
  readonly supporting: string;
  readonly vitals: Vitals;
  readonly vital_trends: VitalTrends;
  readonly labs: LabPanel;
  readonly sort_tier: Tier;
  readonly tier_status: TierStatus[];
  readonly tier_b: TierBData | null;
  readonly tier_c: TierCData | null;
  readonly escalation_reasons: readonly EscalationReason[];
  readonly synthetic: boolean;
  readonly signal_quality: number;
  readonly last_update_s: number;
}

export interface AbstainedRow {
  readonly id: string;
  readonly name: string;
  readonly age: number | null;
  readonly sex: string | null;
  readonly bed: string;
  readonly admitting_context: string;
  readonly reason: string;
  readonly instruction: string;
  readonly synthetic: boolean;
}

// --- API responses ---

export interface WardResponse {
  readonly ward: string;
  readonly clinician: string;
  readonly shift: string;
  readonly receiving_data: boolean;
  readonly sort_tier: Tier;
  readonly tier_status: TierStatus[];
  readonly ranked: ScoreRow[];
  readonly abstained: AbstainedRow[];
}

export interface PatientDetail extends ScoreRow {
  readonly vital_history: VitalHistoryFull;
  readonly tier_breakdown: {
    readonly tier_a: { readonly score: number; readonly label: string } | null;
    readonly tier_b: TierBData | null;
    readonly tier_c: TierCData | null;
  };
}

// --- Clinical notes ---

export interface ClinicalNote {
  readonly id: string;
  readonly patient_id: string;
  readonly author: string;
  readonly role: string;
  readonly timestamp: string;
  readonly content: string;
}

// --- Session ---

export type SessionRole = "rn" | "md" | "charge_rn";

export interface Session {
  readonly clinician_id: string;
  readonly ward: string;
  readonly role: SessionRole;
}

// --- Station form inputs (STUB: replaced by API in prompt 04) ---
// Fields follow Philippine DOH and PhilHealth requirements.

export type AdmissionCondition = "ambulatory" | "wheelchair" | "stretcher";

export interface AdmitPatientInput {
  // Identity (DOH face sheet)
  readonly lastName: string;
  readonly firstName: string;
  readonly middleName?: string;
  readonly nameExtension?: string;              // Jr, Sr, III
  readonly dateOfBirth: string;                 // ISO date (YYYY-MM-DD)
  readonly age: number;
  readonly sex: "M" | "F";
  readonly civilStatus?: "single" | "married" | "widowed" | "separated";
  readonly contactNumber?: string;
  readonly philhealthPin?: string;              // XX-XXXXXXXXX-X (2-9-1)
  // Admission details
  readonly bed: string;
  readonly admissionRoute: "er_triage" | "direct_admission" | "transfer";
  readonly conditionOnAdmission?: AdmissionCondition;
  readonly chiefComplaint: string;
  readonly admittingContext: string;             // Admitting diagnosis / clinical context
  readonly attendingPhysician: string;
  readonly allergies?: string;                  // Free text or "NKDA"
  // CV-specific
  readonly weightKg?: number;
  readonly heightCm?: number;
  // Initial vitals (nurse-entered)
  readonly initialBp?: string;
  readonly initialAvpu?: "A" | "V" | "P" | "U";
}

export interface PartialLabInput {
  // Cardiac biomarkers
  readonly troponin?: number;
  readonly ck_mb?: number;
  readonly bnp?: number;
  readonly nt_probnp?: number;
  // Electrolytes
  readonly sodium?: number;
  readonly potassium?: number;
  readonly chloride?: number;
  readonly magnesium?: number;
  readonly calcium?: number;
  // Renal
  readonly creatinine?: number;
  readonly bun?: number;
  // Hematology
  readonly hemoglobin?: number;
  readonly hematocrit?: number;
  readonly wbc?: number;
  readonly platelet_count?: number;
  // Coagulation
  readonly pt?: number;
  readonly inr?: number;
  // Liver (PH naming)
  readonly sgpt?: number;
  readonly sgot?: number;
  // Metabolic
  readonly blood_glucose?: number;
  readonly lactate?: number;
}

// --- Extraction results (STUB: replaced by OCR pipeline in prompt 04) ---

export interface LabExtractionResult {
  readonly values: PartialLabInput;
  readonly confidence: Record<string, number>;
  readonly synthetic: boolean;
  readonly model_id: string;
}

export interface PatientExtractionResult {
  readonly values: Partial<AdmitPatientInput>;
  readonly confidence: Record<string, number>;
  readonly synthetic: boolean;
  readonly model_id: string;
}
