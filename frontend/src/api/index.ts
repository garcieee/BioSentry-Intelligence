/**
 * Owns: provider selection and public API surface for the frontend.
 * Must never: contain business logic or endpoint definitions.
 * Invariants: components import from here, never from providers or data/fixtures directly.
 */

import type { ApiProvider } from "./contract";
import { fixtureProvider, setActiveClinician } from "./providers/fixture";
import { httpProvider } from "./providers/http";
import { setAuthToken } from "./client";

const USE_FIXTURES = !import.meta.env.VITE_API_URL;

const provider: ApiProvider = USE_FIXTURES ? fixtureProvider : httpProvider;

export const getWard = provider.getWard;
export const getPatient = provider.getPatient;
export const getNotes = provider.getNotes;
export const addNote = provider.addNote;
export const deleteNote = provider.deleteNote;
export const listAllPatients = provider.listAllPatients;
export const admitPatient = provider.admitPatient;
export const enterLabResults = provider.enterLabResults;
export const extractLabsFromFile = provider.extractLabsFromFile;
export const extractPatientFromFile = provider.extractPatientFromFile;

/**
 * Call on sign-in. For fixtures, sets the clinician filter.
 * For http, sets the bearer token (clinician filtering is server-side).
 */
export function initSession(clinicianId: string, token?: string): void {
  if (USE_FIXTURES) {
    setActiveClinician(clinicianId);
  } else {
    setAuthToken(token ?? clinicianId);
  }
}

export function clearSession(): void {
  if (USE_FIXTURES) {
    setActiveClinician(null);
  } else {
    setAuthToken(null);
  }
}

export { setAuthToken, getAuthToken, ApiError } from "./client";
export type { ApiProvider } from "./contract";
