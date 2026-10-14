import type { BloodPressure } from "../types";

/**
 * "88/52": the display text of a structured blood pressure. Display only: the string is
 * never parsed back into numbers (D10).
 */
export function formatBloodPressure(bp: BloodPressure): string {
  return `${bp.systolic}/${bp.diastolic}`;
}
