/**
 * Owns: adapting data/fixtures.ts to the ApiProvider interface.
 * Must never: contain business logic or data. Pure delegation.
 * Invariants: inherits from fixtures (I1, I2, I4, I6).
 */

import type { ApiProvider } from "../contract";
import * as fixtures from "../../data/fixtures";

export const setActiveClinician = fixtures.setActiveClinician;

export const fixtureProvider: ApiProvider = {
  getWard: fixtures.getWard,
  getPatient: fixtures.getPatient,
  getNotes: fixtures.getNotes,
  addNote: fixtures.addNote,
  deleteNote: fixtures.deleteNote,
  listAllPatients: fixtures.listAllPatients,
  admitPatient: fixtures.admitPatient,
  enterLabResults: fixtures.enterLabResults,
  extractLabsFromFile: fixtures.extractLabsFromFile,
  extractPatientFromFile: fixtures.extractPatientFromFile,
};
