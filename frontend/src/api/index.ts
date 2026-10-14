/**
 * Owns: provider selection and public API surface for the frontend.
 * Must never: contain business logic or endpoint definitions.
 * Invariants: components import from here, never from providers or data/fixtures directly.
 *
 * The provider is chosen at BUILD time by VITE_API_URL. An HTTP-mode build carries neither the
 * fixture provider nor the synthetic dataset: the fixture provider is only ever reached through
 * a dynamic import inside a branch the bundler removes when VITE_API_URL is set (a test builds
 * both modes and fails if the dataset appears in the HTTP one). In fixture mode it is a
 * separate chunk, loaded on first use.
 */

import type { ApiProvider } from "./contract";
import { httpProvider } from "./providers/http";
import { setAuthToken } from "./client";

const USE_FIXTURES = !import.meta.env.VITE_API_URL;

type FixtureModule = typeof import("./providers/fixture");

// One promise, so a session set at sign-in is applied before the first call that follows it.
let fixtureModule: Promise<FixtureModule> | undefined;
const fixtures = (): Promise<FixtureModule> => (fixtureModule ??= import("./providers/fixture"));

/**
 * The fixture provider, loaded on first use. Every method is already asynchronous, so loading
 * lazily changes nothing for callers. Listed method by method on purpose: adding a method to
 * ApiProvider is a compile error here until it is forwarded.
 */
function lazyFixtureProvider(): ApiProvider {
  return {
    getWard: () => fixtures().then((m) => m.fixtureProvider.getWard()),
    getPatient: (id) => fixtures().then((m) => m.fixtureProvider.getPatient(id)),
    getNotes: (patientId) => fixtures().then((m) => m.fixtureProvider.getNotes(patientId)),
    addNote: (patientId, author, role, content) =>
      fixtures().then((m) => m.fixtureProvider.addNote(patientId, author, role, content)),
    deleteNote: (patientId, noteId) =>
      fixtures().then((m) => m.fixtureProvider.deleteNote(patientId, noteId)),
    listAllPatients: () => fixtures().then((m) => m.fixtureProvider.listAllPatients()),
    admitPatient: (input) => fixtures().then((m) => m.fixtureProvider.admitPatient(input)),
    enterLabResults: (patientId, labs) =>
      fixtures().then((m) => m.fixtureProvider.enterLabResults(patientId, labs)),
    recordVitals: (patientId, input) =>
      fixtures().then((m) => m.fixtureProvider.recordVitals(patientId, input)),
    extractLabsFromFile: (file) =>
      fixtures().then((m) => m.fixtureProvider.extractLabsFromFile(file)),
    extractPatientFromFile: (file) =>
      fixtures().then((m) => m.fixtureProvider.extractPatientFromFile(file)),
  };
}

const provider: ApiProvider = USE_FIXTURES ? lazyFixtureProvider() : httpProvider;

export const getWard = provider.getWard;
export const getPatient = provider.getPatient;
export const getNotes = provider.getNotes;
export const addNote = provider.addNote;
export const deleteNote = provider.deleteNote;
export const listAllPatients = provider.listAllPatients;
export const admitPatient = provider.admitPatient;
export const enterLabResults = provider.enterLabResults;
export const recordVitals = provider.recordVitals;

/**
 * Whether this build can record nurse-entered vitals. Only the API re-ranks (D4: the frontend
 * never computes a score), so the fixture provider offers no entry; it rejects the call.
 */
export const canRecordVitals = !USE_FIXTURES;
export const extractLabsFromFile = provider.extractLabsFromFile;
export const extractPatientFromFile = provider.extractPatientFromFile;

/**
 * Call on sign-in. For fixtures, sets the clinician filter.
 * For http, sets the bearer token (clinician filtering is server-side).
 */
export function initSession(clinicianId: string, token?: string): void {
  if (USE_FIXTURES) {
    void fixtures().then((m) => m.setActiveClinician(clinicianId));
  } else {
    setAuthToken(token ?? clinicianId);
  }
}

export function clearSession(): void {
  if (USE_FIXTURES) {
    void fixtures().then((m) => m.setActiveClinician(null));
  } else {
    setAuthToken(null);
  }
}

export { setAuthToken, getAuthToken, ApiError } from "./client";
export type { ApiProvider } from "./contract";
