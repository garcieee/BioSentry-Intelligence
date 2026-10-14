import type { BloodPressure, Spo2Scale } from "../types";

/**
 * "88/52": the display text of a structured blood pressure. Display only: the string is
 * never parsed back into numbers (D10).
 */
export function formatBloodPressure(bp: BloodPressure): string {
  return `${bp.systolic}/${bp.diastolic}`;
}

/** The NEWS2 air-or-oxygen input, in words rather than a bare true/false. */
export function formatOxygen(onOxygen: boolean): string {
  return onOxygen ? "On oxygen" : "Room air";
}

/** The recorded NEWS2 SpO2 scoring scale (scale 2 is a clinician's decision). */
export function formatSpo2Scale(scale: Spo2Scale): string {
  return `Scale ${scale}`;
}
