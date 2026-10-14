/**
 * Owns: the logic behind the vitals-entry form: validation, what the request will carry, the
 * echo shown before it is sent, and turning a failure into a sentence a nurse can act on.
 * Must never: compute a score or a rank (D4: only the server does), clamp or adjust a value,
 * fill in a field the nurse left blank, or send a value the server did not ask for.
 * Invariants: I1 (a blank field is "not recorded", never zero or a default), I2 (what is
 * sent is a manual entry; the server stamps provenance), I4 (a patient that stays NOT RANKED
 * says why, in the server's words).
 */

import { ApiError } from "../api/client";
import { DIASTOLIC_BOUNDS, SYSTOLIC_BOUNDS } from "../api/bounds";
import type { Acvpu, NurseVitalsInput, VitalsRecorded } from "../types";

// --- The draft: exactly what is in the form, as text and choices ---

export interface VitalsDraft {
  readonly systolic: string;
  readonly diastolic: string;
  readonly acvpu: Acvpu | "";
  readonly oxygen: "" | "air" | "oxygen";
  readonly spo2Scale: "" | "1" | "2";
}

export const EMPTY_DRAFT: VitalsDraft = {
  systolic: "",
  diastolic: "",
  acvpu: "",
  oxygen: "",
  spo2Scale: "",
};

export const ACVPU_CHOICES: readonly { value: Acvpu; label: string }[] = [
  { value: "A", label: "Alert" },
  { value: "C", label: "New confusion" },
  { value: "V", label: "Responds to voice" },
  { value: "P", label: "Responds to pain" },
  { value: "U", label: "Unresponsive" },
];

export interface DraftProblems {
  readonly form?: string;
  readonly systolic?: string;
  readonly diastolic?: string;
  readonly pair?: string;
}

export type Checked =
  | { readonly ok: true; readonly input: NurseVitalsInput }
  | { readonly ok: false; readonly problems: DraftProblems };

const WHOLE_NUMBER = /^\d{1,3}$/;

function wholeNumber(text: string): number | null {
  const trimmed = text.trim();
  return WHOLE_NUMBER.test(trimmed) ? Number(trimmed) : null;
}

/** Bounded entry. The server re-checks everything; this keeps an obvious slip off the wire. */
export function check(draft: VitalsDraft): Checked {
  const systolicText = draft.systolic.trim();
  const diastolicText = draft.diastolic.trim();
  const hasPressure = systolicText !== "" || diastolicText !== "";
  const problems: { -readonly [K in keyof DraftProblems]: DraftProblems[K] } = {};
  let pressure: { systolic: number; diastolic: number } | null = null;

  if (hasPressure) {
    const systolic = systolicText === "" ? null : wholeNumber(systolicText);
    const diastolic = diastolicText === "" ? null : wholeNumber(diastolicText);
    if (systolicText === "") problems.systolic = "Enter the systolic value.";
    else if (systolic === null) problems.systolic = "Whole numbers only.";
    else if (systolic < SYSTOLIC_BOUNDS.min || systolic > SYSTOLIC_BOUNDS.max) {
      problems.systolic = `Systolic must be ${SYSTOLIC_BOUNDS.min} to ${SYSTOLIC_BOUNDS.max}.`;
    }
    if (diastolicText === "") problems.diastolic = "Enter the diastolic value.";
    else if (diastolic === null) problems.diastolic = "Whole numbers only.";
    else if (diastolic < DIASTOLIC_BOUNDS.min || diastolic > DIASTOLIC_BOUNDS.max) {
      problems.diastolic = `Diastolic must be ${DIASTOLIC_BOUNDS.min} to ${DIASTOLIC_BOUNDS.max}.`;
    }
    if (problems.systolic === undefined && problems.diastolic === undefined) {
      if (systolic !== null && diastolic !== null) {
        if (diastolic >= systolic) problems.pair = "Diastolic must be below systolic.";
        else pressure = { systolic, diastolic };
      }
    }
  }

  const nothing =
    !hasPressure && draft.acvpu === "" && draft.oxygen === "" && draft.spo2Scale === "";
  if (nothing) problems.form = "Record at least one value.";
  if (Object.keys(problems).length > 0) return { ok: false, problems };

  const input: NurseVitalsInput = {
    ...(pressure !== null ? pressure : {}),
    ...(draft.acvpu !== "" ? { acvpu: draft.acvpu } : {}),
    ...(draft.oxygen !== "" ? { on_oxygen: draft.oxygen === "oxygen" } : {}),
    ...(draft.spo2Scale !== "" ? { spo2_scale: draft.spo2Scale === "2" ? 2 : 1 } : {}),
  } as NurseVitalsInput;
  return { ok: true, input };
}

// --- What will be stored, before it is sent ---

/** One line per value that will be recorded. A blank field has no line: it stays as it is. */
export function echoLines(input: NurseVitalsInput): string[] {
  const lines: string[] = [];
  if (typeof input.systolic === "number" && typeof input.diastolic === "number") {
    lines.push(`Blood pressure ${input.systolic}/${input.diastolic} mmHg`);
  }
  if (input.acvpu !== undefined && input.acvpu !== null) {
    const label = ACVPU_CHOICES.find((c) => c.value === input.acvpu)?.label ?? input.acvpu;
    lines.push(`Level of consciousness: ${label} (${input.acvpu})`);
  }
  if (input.on_oxygen !== undefined && input.on_oxygen !== null) {
    lines.push(`Oxygen: ${input.on_oxygen ? "on supplemental oxygen" : "room air"}`);
  }
  if (input.spo2_scale !== undefined && input.spo2_scale !== null) {
    lines.push(`SpO2 scale: ${input.spo2_scale}`);
  }
  return lines;
}

/** The echo for a draft as it stands (empty while the draft is not valid). */
export function echoDraft(draft: VitalsDraft): string[] {
  const checked = check(draft);
  return checked.ok ? echoLines(checked.input) : [];
}

// --- What the server said ---

function sentence(text: string): string {
  const trimmed = text.trim();
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

/** The patient's standing after the write, in the server's words. */
export function standing(recorded: VitalsRecorded): string {
  if (recorded.ranked && recorded.rank !== null && recorded.score !== null) {
    return `Ranked #${recorded.rank} with NEWS2 ${recorded.score}.`;
  }
  const reason = recorded.not_ranked_reason ?? "";
  const instruction = recorded.not_ranked_instruction ?? "";
  return `Still not ranked. ${sentence(reason)} ${sentence(instruction)}`.trim();
}

function serverReasons(body: unknown): string[] {
  if (typeof body !== "object" || body === null) return [];
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return [sentence(detail)];
  if (!Array.isArray(detail)) return [];
  const reasons: string[] = [];
  for (const item of detail) {
    if (typeof item !== "object" || item === null) continue;
    const { msg, loc } = item as { msg?: unknown; loc?: unknown };
    if (typeof msg !== "string") continue;
    const field = Array.isArray(loc) && typeof loc[loc.length - 1] === "string" ? loc[loc.length - 1] : null;
    reasons.push(sentence(field !== null && field !== "body" ? `${field}: ${msg}` : msg));
  }
  return reasons;
}

/** A failure as one sentence for the nurse. Never echoes the rejected input back. */
export function explainFailure(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return "You are not signed in. Sign in again, then record the values.";
      case 403:
        return "The server does not recognise this sign-in. Sign in again.";
      case 404:
        return "This patient is not on your list. Nothing was recorded.";
      case 422: {
        const why = serverReasons(error.body).join(" ");
        return `Not recorded. ${why || "The server rejected these values."}`.trim();
      }
      default:
        return `The server could not record this (HTTP ${error.status}). Check the ward before entering it again.`;
    }
  }
  return "Could not reach the server. Check the connection; the values may not have been recorded.";
}

// --- The whole flow, with the network as a dependency ---

export type Outcome =
  | { readonly kind: "invalid"; readonly problems: DraftProblems }
  | { readonly kind: "recorded"; readonly recorded: VitalsRecorded }
  | { readonly kind: "failed"; readonly message: string };

export type RecordVitals = (patientId: string, input: NurseVitalsInput) => Promise<VitalsRecorded>;

/** Check, send, and describe what happened. An invalid draft never reaches the network. */
export async function submitDraft(
  patientId: string,
  draft: VitalsDraft,
  record: RecordVitals,
): Promise<Outcome> {
  const checked = check(draft);
  if (!checked.ok) return { kind: "invalid", problems: checked.problems };
  try {
    return { kind: "recorded", recorded: await record(patientId, checked.input) };
  } catch (error) {
    return { kind: "failed", message: explainFailure(error) };
  }
}
