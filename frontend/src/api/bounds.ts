/**
 * Owns: the physical bounds the server enforces on a nurse-typed blood pressure.
 * Must never: be used to clamp. A value outside these bounds is rejected, never adjusted.
 * Invariants: I1. The server is the authority (backend services/patients.py); these exist so
 * the entry form and the fixture admission check say the same thing. The HTTP leg of the
 * contract suite pins both edges of both bounds against the running server, so a change on
 * either side fails a test.
 *
 * The floor is deliberately low: a true critical reading such as 45/20 must be recordable,
 * because refusing it would leave the patient silently NOT RANKED.
 */

export const SYSTOLIC_BOUNDS = { min: 20, max: 300 } as const;
export const DIASTOLIC_BOUNDS = { min: 10, max: 200 } as const;
