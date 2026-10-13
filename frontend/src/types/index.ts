/**
 * Contract types for the BioSentry dashboard.
 *
 * Source of truth: backend/src/biosentry/schemas (Pydantic) -> contracts/openapi.json
 * -> ./generated.ts. Never hand-edit generated.ts; regenerate with `make contract`.
 * CI (`contract-drift`) fails when the committed file differs from a fresh generation.
 *
 * The only hand-written shapes here are the generic Measurement<T> / MeasurementValue<T>
 * wrappers components use. The assertions at the bottom fail typecheck if they drift from
 * the generated concrete measurement types.
 *
 * Invariants: I1 (missing is missing), I2 (provenance on every value),
 * I3 (tier separation), I4 (abstention is not a score), I6 (synthetic flag).
 */

import type {
  Acvpu,
  AcvpuMeasurement,
  BloodPressure,
  BloodPressureMeasurement,
  FlagMeasurement,
  NumberMeasurement,
  Provenance,
  Spo2Scale,
  Spo2ScaleMeasurement,
} from "./generated";

export type {
  AbstainedRow,
  Acvpu,
  AdmissionCondition,
  AdmissionRoute,
  AdmitPatientInput,
  BloodPressure,
  CivilStatus,
  ClinicalNote,
  EscalationReason,
  EscalationRule,
  FindingDirection,
  LabExtractionResult,
  LabPanel,
  PartialAdmitPatientInput,
  PartialLabInput,
  PatientDetail,
  PatientExtractionResult,
  Provenance,
  ProvenanceSource,
  QualityLevel,
  ScoreRow,
  Session,
  SessionRole,
  Sex,
  Spo2Scale,
  Tier,
  TierAScore,
  TierBData,
  TierBFinding,
  TierBreakdown,
  TierCAttribution,
  TierCData,
  TierCInput,
  TierStatus,
  Trend,
  VitalHistory,
  VitalHistoryFull,
  VitalTrends,
  Vitals,
  WardResponse,
} from "./generated";

// --- Measurement primitives (generic wrappers over the generated concrete types) ---

export type MeasurementValue<T> =
  | { readonly present: true; readonly value: T }
  | { readonly present: false; readonly reason: string };

export interface Measurement<T> {
  readonly data: MeasurementValue<T>;
  readonly provenance: Provenance;
}

// --- Drift guard: each generated measurement must match Measurement<its value type> ---

type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
type MustBeTrue<T extends true> = T;

export type MeasurementContractChecks = [
  MustBeTrue<Same<NumberMeasurement, Measurement<number>>>,
  MustBeTrue<Same<FlagMeasurement, Measurement<boolean>>>,
  MustBeTrue<Same<AcvpuMeasurement, Measurement<Acvpu>>>,
  MustBeTrue<Same<Spo2ScaleMeasurement, Measurement<Spo2Scale>>>,
  MustBeTrue<Same<BloodPressureMeasurement, Measurement<BloodPressure>>>,
];
