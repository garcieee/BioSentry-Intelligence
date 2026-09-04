/**
 * Owns: mapping ApiProvider methods to real HTTP endpoints.
 * Must never: hold state, cache, or retry. The fetch wrapper in client.ts handles transport.
 * Invariants: I2 (provenance must arrive from server, not be fabricated here).
 *
 * Endpoints align with the contract defined in prompt 03:
 *   GET  /wards/{ward}/rows
 *   GET  /patients/{id}
 *   POST /session
 *   plus notes, labs, and extraction sub-resources.
 *
 * Stubs raise -- they do not return plausible values (house rule).
 */

import type { ApiProvider } from "../contract";
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
} from "../../types";
import {
  deleteRequest,
  fetchJson,
  postJson,
  uploadFile,
} from "../client";

export const httpProvider: ApiProvider = {
  getWard(): Promise<WardResponse> {
    return fetchJson<WardResponse>("/wards/W4/rows");
  },

  getPatient(id: string): Promise<PatientDetail | null> {
    return fetchJson<PatientDetail | null>(`/patients/${id}`);
  },

  getNotes(patientId: string): Promise<ClinicalNote[]> {
    return fetchJson<ClinicalNote[]>(`/patients/${patientId}/notes`);
  },

  addNote(
    patientId: string,
    author: string,
    role: string,
    content: string,
  ): Promise<ClinicalNote> {
    return postJson<ClinicalNote>(`/patients/${patientId}/notes`, {
      author,
      role,
      content,
    });
  },

  deleteNote(patientId: string, noteId: string): Promise<void> {
    return deleteRequest(`/patients/${patientId}/notes/${noteId}`);
  },

  listAllPatients(): Promise<
    Array<{ id: string; name: string; bed: string; ranked: boolean }>
  > {
    return fetchJson(`/patients`);
  },

  admitPatient(input: AdmitPatientInput): Promise<AbstainedRow> {
    return postJson<AbstainedRow>(`/patients`, input);
  },

  enterLabResults(
    patientId: string,
    labs: PartialLabInput,
  ): Promise<LabPanel> {
    return postJson<LabPanel>(`/patients/${patientId}/labs`, labs);
  },

  extractLabsFromFile(file: File): Promise<LabExtractionResult> {
    return uploadFile<LabExtractionResult>(`/extract/labs`, file);
  },

  extractPatientFromFile(file: File): Promise<PatientExtractionResult> {
    return uploadFile<PatientExtractionResult>(`/extract/patient`, file);
  },
};
