/**
 * Owns: the shape every data provider must satisfy.
 * Must never: contain implementation, import provider code, or reference env vars.
 * Invariants: I1 (missing is missing), I2 (provenance on every value), I4 (abstention is a type).
 */

import type {
  AbstainedRow,
  AdmitPatientInput,
  ClinicalNote,
  LabExtractionResult,
  LabPanel,
  PartialLabInput,
  PatientDetail,
  PatientExtractionResult,
  WardResponse,
} from "../types";

export interface ApiProvider {
  getWard(): Promise<WardResponse>;
  getPatient(id: string): Promise<PatientDetail | null>;
  getNotes(patientId: string): Promise<ClinicalNote[]>;
  addNote(
    patientId: string,
    author: string,
    role: string,
    content: string,
  ): Promise<ClinicalNote>;
  deleteNote(patientId: string, noteId: string): Promise<void>;
  listAllPatients(): Promise<
    Array<{ id: string; name: string; bed: string; ranked: boolean }>
  >;
  admitPatient(input: AdmitPatientInput): Promise<AbstainedRow>;
  enterLabResults(
    patientId: string,
    labs: PartialLabInput,
  ): Promise<LabPanel>;
  extractLabsFromFile(file: File): Promise<LabExtractionResult>;
  extractPatientFromFile(file: File): Promise<PatientExtractionResult>;
}
