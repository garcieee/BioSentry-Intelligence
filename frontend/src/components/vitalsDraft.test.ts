import { describe, expect, it } from "vitest";
import { DIASTOLIC_BOUNDS, SYSTOLIC_BOUNDS } from "../api/bounds";
import { ApiError } from "../api/client";
import type { NurseVitalsInput, VitalsRecorded } from "../types";
import {
  EMPTY_DRAFT,
  type VitalsDraft,
  check,
  echoDraft,
  echoLines,
  explainFailure,
  standing,
  submitDraft,
} from "./vitalsDraft";

const draft = (over: Partial<VitalsDraft>): VitalsDraft => ({ ...EMPTY_DRAFT, ...over });

function inputOf(d: VitalsDraft): NurseVitalsInput {
  const checked = check(d);
  if (!checked.ok) throw new Error(`expected a valid draft, got ${JSON.stringify(checked.problems)}`);
  return checked.input;
}

function problemsOf(d: VitalsDraft) {
  const checked = check(d);
  if (checked.ok) throw new Error("expected problems");
  return checked.problems;
}

describe("a blank draft says what it is: nothing", () => {
  it("is refused as a whole, not sent as zeros", () => {
    expect(problemsOf(EMPTY_DRAFT).form).toBe("Record at least one value.");
  });

  it("treats whitespace as blank", () => {
    expect(problemsOf(draft({ systolic: "  ", diastolic: " " })).form).toBeDefined();
  });
});

describe("what a valid draft sends", () => {
  it("carries only what was entered, with nothing null, zero or undefined", () => {
    const only = [
      [draft({ acvpu: "U" }), { acvpu: "U" }],
      [draft({ oxygen: "oxygen" }), { on_oxygen: true }],
      [draft({ oxygen: "air" }), { on_oxygen: false }], // false is a recorded value
      [draft({ spo2Scale: "2" }), { spo2_scale: 2 }],
      [draft({ systolic: "130", diastolic: "84" }), { systolic: 130, diastolic: 84 }],
    ] as const;
    for (const [d, expected] of only) {
      expect(inputOf(d)).toEqual(expected);
    }
  });

  it("sends everything entered, and the pair together", () => {
    const d = draft({ systolic: "45", diastolic: "20", acvpu: "A", oxygen: "oxygen", spo2Scale: "1" });
    expect(inputOf(d)).toEqual({
      systolic: 45,
      diastolic: 20,
      acvpu: "A",
      on_oxygen: true,
      spo2_scale: 1,
    });
  });

  it("trims what was typed", () => {
    expect(inputOf(draft({ systolic: " 120 ", diastolic: "80 " }))).toEqual({
      systolic: 120,
      diastolic: 80,
    });
  });
});

describe("bounded blood pressure entry (the server's bounds, both edges)", () => {
  const { min: sMin, max: sMax } = SYSTOLIC_BOUNDS;
  const { min: dMin, max: dMax } = DIASTOLIC_BOUNDS;

  it("accepts the floor, the ceiling and a true critical reading", () => {
    for (const [s, d] of [
      [sMin, dMin],
      [sMax, dMax],
      [45, 20],
    ]) {
      expect(check(draft({ systolic: String(s), diastolic: String(d) })).ok, `${s}/${d}`).toBe(true);
    }
  });

  it("rejects one past each bound and never clamps", () => {
    expect(problemsOf(draft({ systolic: String(sMin - 1), diastolic: String(dMin) })).systolic).toBeDefined();
    expect(problemsOf(draft({ systolic: String(sMax + 1), diastolic: "80" })).systolic).toBeDefined();
    expect(problemsOf(draft({ systolic: "120", diastolic: String(dMin - 1) })).diastolic).toBeDefined();
    expect(problemsOf(draft({ systolic: String(sMax), diastolic: String(dMax + 1) })).diastolic).toBeDefined();
  });

  it("states the bounds in the message", () => {
    expect(problemsOf(draft({ systolic: "5", diastolic: "80" })).systolic).toContain("20 to 300");
    expect(problemsOf(draft({ systolic: "120", diastolic: "5" })).diastolic).toContain("10 to 200");
  });

  it("needs diastolic below systolic", () => {
    expect(problemsOf(draft({ systolic: "80", diastolic: "80" })).pair).toBeDefined();
    expect(problemsOf(draft({ systolic: "80", diastolic: "120" })).pair).toBeDefined();
  });

  it("is a pair: half of one is refused", () => {
    expect(problemsOf(draft({ systolic: "130" })).diastolic).toBeDefined();
    expect(problemsOf(draft({ diastolic: "80" })).systolic).toBeDefined();
  });

  it("takes whole numbers only", () => {
    for (const text of ["12.5", "-5", "1e2", "abc", "1,20", "0x10", "١٢٠", "1000"]) {
      expect(problemsOf(draft({ systolic: text, diastolic: "80" })).systolic, text).toBeDefined();
    }
  });

  it("rejects zero: zero is missing, not a reading", () => {
    expect(problemsOf(draft({ systolic: "0", diastolic: "0" })).systolic).toBeDefined();
  });
});

describe("the echo of what will be stored", () => {
  it("lists exactly the entered values, in words", () => {
    const input: NurseVitalsInput = {
      systolic: 130,
      diastolic: 84,
      acvpu: "C",
      on_oxygen: false,
      spo2_scale: 2,
    };
    expect(echoLines(input)).toEqual([
      "Blood pressure 130/84 mmHg",
      "Level of consciousness: New confusion (C)",
      "Oxygen: room air",
      "SpO2 scale: 2",
    ]);
  });

  it("is empty for a draft that cannot be sent, so nothing is promised that will not be stored", () => {
    expect(echoDraft(draft({ systolic: "130" }))).toEqual([]);
    expect(echoDraft(EMPTY_DRAFT)).toEqual([]);
    expect(echoDraft(draft({ acvpu: "A" }))).toEqual(["Level of consciousness: Alert (A)"]);
  });
});

describe("the server's answer, in its own words", () => {
  const recorded = (over: Partial<VitalsRecorded>): VitalsRecorded => ({
    patient_id: "p-004",
    blood_pressure: null,
    consciousness: null,
    supplemental_o2: null,
    spo2_scale: null,
    ranked: true,
    rank: 3,
    score: 0,
    not_ranked_reason: null,
    not_ranked_instruction: null,
    ...over,
  });

  it("states a rank and a score", () => {
    expect(standing(recorded({}))).toBe("Ranked #3 with NEWS2 0.");
  });

  it("states why a patient is still NOT RANKED and what to do, with no score", () => {
    const text = standing(
      recorded({
        ranked: false,
        rank: null,
        score: null,
        not_ranked_reason: "No device data",
        not_ranked_instruction: "Apply the patch and verify the signal",
      }),
    );
    expect(text).toBe("Still not ranked. No device data. Apply the patch and verify the signal.");
  });
});

describe("a failure is one sentence the nurse can act on", () => {
  const failure = (status: number, body: unknown) => explainFailure(new ApiError(status, "x", body));

  it("explains identity and scope", () => {
    expect(failure(401, { detail: "Authentication required" })).toContain("Sign in again");
    expect(failure(403, { detail: "Unknown identity" })).toContain("Sign in again");
    expect(failure(404, { detail: "Not found" })).toContain("not on your list");
  });

  it("shows the server's reason for a rejected value", () => {
    expect(failure(422, { detail: "systolic 19 is outside 20-300" })).toBe(
      "Not recorded. systolic 19 is outside 20-300.",
    );
  });

  it("shows validation reasons by field and never echoes the rejected input", () => {
    const text = failure(422, {
      detail: [
        { type: "int_type", loc: ["body", "systolic"], msg: "Input should be a valid integer", input: "9187x" },
        { type: "extra_forbidden", loc: ["body", "heart_rate"], msg: "Extra inputs are not permitted", input: 70 },
      ],
    });
    expect(text).toContain("systolic: Input should be a valid integer.");
    expect(text).toContain("heart_rate: Extra inputs are not permitted.");
    expect(text).not.toContain("9187x");
  });

  it("still says something useful when the body is not what was expected", () => {
    expect(failure(422, null)).toContain("The server rejected these values.");
    expect(failure(422, { detail: 7 })).toContain("The server rejected these values.");
  });

  it("does not claim nothing was stored when it cannot know", () => {
    expect(failure(500, {})).toContain("Check the ward");
    expect(explainFailure(new TypeError("Failed to fetch"))).toContain("may not have been recorded");
  });
});

describe("submitting", () => {
  const ranked: VitalsRecorded = {
    patient_id: "p-004",
    blood_pressure: null,
    consciousness: null,
    supplemental_o2: null,
    spo2_scale: null,
    ranked: true,
    rank: 2,
    score: 3,
    not_ranked_reason: null,
    not_ranked_instruction: null,
  };

  it("never reaches the network with an invalid draft", async () => {
    const calls: unknown[] = [];
    const outcome = await submitDraft("p-004", draft({ systolic: "400", diastolic: "80" }), async (...args) => {
      calls.push(args);
      return ranked;
    });
    expect(outcome.kind).toBe("invalid");
    expect(calls).toEqual([]);
  });

  it("sends the checked input once, for the right patient", async () => {
    const calls: [string, NurseVitalsInput][] = [];
    const outcome = await submitDraft("p-004", draft({ systolic: "45", diastolic: "20" }), async (id, input) => {
      calls.push([id, input]);
      return ranked;
    });
    expect(calls).toEqual([["p-004", { systolic: 45, diastolic: 20 }]]);
    expect(outcome).toEqual({ kind: "recorded", recorded: ranked });
  });

  it("turns a rejection into a message, without throwing", async () => {
    const outcome = await submitDraft("p-004", draft({ acvpu: "U" }), async () => {
      throw new ApiError(422, "Unprocessable", { detail: "no" });
    });
    expect(outcome).toEqual({ kind: "failed", message: "Not recorded. no." });
  });

  it("turns a network failure into a message", async () => {
    const outcome = await submitDraft("p-004", draft({ acvpu: "U" }), async () => {
      throw new TypeError("Failed to fetch");
    });
    expect(outcome.kind).toBe("failed");
  });
});
