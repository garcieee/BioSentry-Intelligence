/**
 * One contract suite, two providers (PLAN CP6/CP8): every assertion runs against the fixture
 * provider and, when VITE_API_URL names a running API, against the HTTP provider too.
 *
 *   make http-contract        # starts the API on :8765, runs this file against both
 *
 * The same assertions hold for both: server-side scope, fail-closed identity, ordering by the
 * arbiter, gaps as null, notes, labs, admission. Behaviour that cannot match (the fixture
 * provider has no 401/403, only "sees nobody") is asserted as "rejected or empty".
 */

import { describe, expect, it } from "vitest";
import synthetic from "../../../data/synthetic/synthetic.json";
import type { AdmitPatientInput } from "../types";
import { EMPTY_DRAFT, check } from "../components/vitalsDraft";
import { DIASTOLIC_BOUNDS, SYSTOLIC_BOUNDS } from "./bounds";
import { setAuthToken } from "./client";
import type { ApiProvider } from "./contract";
import { fixtureProvider, setActiveClinician } from "./providers/fixture";
import { httpProvider } from "./providers/http";

interface Harness {
  readonly name: string;
  readonly provider: ApiProvider;
  signIn(clinicianId: string | null): void;
}

const API_URL = import.meta.env.VITE_API_URL as string | undefined;

const harnesses: Harness[] = [
  {
    name: "fixture provider",
    provider: fixtureProvider,
    signIn: (id) => setActiveClinician(id),
  },
  ...(API_URL
    ? [
        {
          name: `http provider (${API_URL})`,
          provider: httpProvider,
          signIn: (id: string | null) => setAuthToken(id),
        },
      ]
    : []),
];

// The committed dataset is the reference both providers serve.
const reference = synthetic as unknown as {
  ranked: { id: string; score: number; escalation_reasons: { text: string }[] }[];
  abstained: { id: string; reason: string; instruction: string }[];
  clinicians: Record<string, { patients: string[] }>;
};
const ORIGINAL_IDS = new Set([
  ...reference.ranked.map((r) => r.id),
  ...reference.abstained.map((a) => a.id),
]);
const ARBITER_ORDER = reference.ranked.map((r) => r.id);
const original = (ids: string[]) => ids.filter((id) => ORIGINAL_IDS.has(id));

async function attempt<T>(run: () => Promise<T>): Promise<{ ok: true; value: T } | { ok: false }> {
  try {
    return { ok: true, value: await run() };
  } catch {
    return { ok: false };
  }
}

const admission = (overrides: Partial<AdmitPatientInput> = {}): AdmitPatientInput => ({
  lastName: "Contract",
  firstName: "Suite",
  dateOfBirth: "1970-01-01",
  age: 55,
  sex: "F",
  bed: "9Z",
  admissionRoute: "direct_admission",
  chiefComplaint: "contract test",
  admittingContext: "contract test",
  attendingPhysician: "Dr Test",
  ...overrides,
});

describe.each(harnesses)("$name", ({ provider, signIn }) => {
  it("the charge nurse sees all twelve, ranked in the arbiter's order", async () => {
    signIn("rn-manalo");
    const ward = await provider.getWard();
    expect(original(ward.ranked.map((r) => r.id))).toEqual(ARBITER_ORDER);
    expect(ward.ranked.map((r) => r.rank)).toEqual(ward.ranked.map((_, i) => i + 1));
    expect(original(ward.abstained.map((a) => a.id)).sort()).toEqual(
      reference.abstained.map((a) => a.id).sort(),
    );
    expect(ward.sort_tier).toBe("A");
  });

  it.each(Object.entries(reference.clinicians))(
    "%s sees exactly their own patients, in the same relative order",
    async (clinician, { patients }) => {
      signIn(clinician);
      const ward = await provider.getWard();
      const shown = original([...ward.ranked, ...ward.abstained].map((p) => p.id));
      expect(shown.sort()).toEqual([...patients].sort());
      expect(original(ward.ranked.map((r) => r.id))).toEqual(
        ARBITER_ORDER.filter((id) => patients.includes(id)),
      );
      const listed = original((await provider.listAllPatients()).map((p) => p.id));
      expect(listed.sort()).toEqual([...patients].sort());
    },
  );

  it("reasons and scores come from the arbiter: the dataset's text, row by row", async () => {
    signIn("rn-manalo");
    const ward = await provider.getWard();
    for (const expected of reference.ranked) {
      const row = ward.ranked.find((r) => r.id === expected.id);
      expect(row, expected.id).toBeDefined();
      expect(row!.score, expected.id).toBe(expected.score);
      expect(row!.escalation_reasons.map((e) => e.text), expected.id).toEqual(
        expected.escalation_reasons.map((e) => e.text),
      );
    }
    for (const expected of reference.abstained) {
      const row = ward.abstained.find((a) => a.id === expected.id);
      expect(row?.reason, expected.id).toBe(expected.reason);
      expect(row?.instruction, expected.id).toBe(expected.instruction);
    }
  });

  it("a patient that is not yours is not found: detail, notes, note writes and labs", async () => {
    signIn("md-aquino");
    expect(await provider.getPatient("p-001")).toBeNull();
    expect(await provider.getPatient("p-999")).toBeNull();
    expect((await attempt(() => provider.getNotes("p-001"))).ok).toBe(false);
    expect((await attempt(() => provider.addNote("p-001", "x", "RN", "x"))).ok).toBe(false);
    expect((await attempt(() => provider.deleteNote("p-001", "n-001"))).ok).toBe(false);
    expect((await attempt(() => provider.enterLabResults("p-001", { potassium: 4 }))).ok).toBe(false);
  });

  it.each([
    ["no identity", null],
    ["an identity that names nobody", "rn-nobody"],
  ])("%s never sees everyone", async (_label, identity) => {
    signIn(identity);
    const ward = await attempt(() => provider.getWard());
    if (ward.ok) {
      expect(ward.value.ranked).toHaveLength(0);
      expect(ward.value.abstained).toHaveLength(0);
    }
    const listed = await attempt(() => provider.listAllPatients());
    if (listed.ok) expect(listed.value).toHaveLength(0);
    const detail = await attempt(() => provider.getPatient("p-001"));
    if (detail.ok) expect(detail.value).toBeNull();
  });

  it("gaps are null in the history and never zero", async () => {
    signIn("rn-manalo");
    const detail = await provider.getPatient("p-006");
    expect(detail).not.toBeNull();
    const heart = detail!.vital_history.heart_rate.map((p) => p.value);
    expect(heart.filter((v) => v === null)).toHaveLength(3);
    for (const series of Object.values(detail!.vital_history)) {
      for (const point of series) expect(point.value === null || point.value > 0).toBe(true);
    }
    for (const series of Object.values(detail!.vital_trends)) {
      for (const v of series) expect(v === null || v > 0).toBe(true);
    }
  });

  it("a note round-trips: newest first, synthetic, and deletable", async () => {
    signIn("rn-manalo");
    const content = `contract-note-${Date.now()}`;
    const note = await provider.addNote("p-003", "RN Contract", "RN", content);
    expect(note.synthetic).toBe(true);
    expect(note.patient_id).toBe("p-003");
    const listed = await provider.getNotes("p-003");
    expect(listed[0].content).toBe(content);
    await provider.deleteNote("p-003", note.id);
    expect((await provider.getNotes("p-003")).map((n) => n.id)).not.toContain(note.id);
  });

  it("lab entry updates only what was entered and keeps the panel as stale as its oldest lab", async () => {
    signIn("rn-manalo");
    const before = (await provider.getPatient("p-011"))!.labs;
    expect(before.freshness_hours).toBe(36);
    const panel = await provider.enterLabResults("p-011", { potassium: 4.1 });
    expect(panel.potassium?.data.present && panel.potassium.data.value).toBe(4.1);
    expect(panel.sodium?.data.present).toBe(true); // untouched
    expect(panel.troponin).toBeNull(); // omitted stays missing, never zero
    expect(panel.freshness_hours).toBe(36);
  });

  it("a negative lab is rejected", async () => {
    signIn("rn-manalo");
    expect((await attempt(() => provider.enterLabResults("p-011", { potassium: -1 }))).ok).toBe(false);
  });

  it("an admitted patient is NOT RANKED, visible to the admitting clinician only", async () => {
    signIn("rn-delacruz");
    const row = await provider.admitPatient(admission({ initialBp: "120/80" }));
    // NOT RANKED with a reason and an instruction about the patch; no score, no rank.
    expect(row.reason.length).toBeGreaterThan(0);
    expect(row.instruction.toLowerCase()).toContain("patch");
    expect(Object.keys(row)).not.toContain("score");
    expect(Object.keys(row)).not.toContain("rank");
    expect(row.synthetic).toBe(true);
    const mine = await provider.getWard();
    expect(mine.abstained.map((a) => a.id)).toContain(row.id);
    signIn("rn-reyes");
    const theirs = await provider.getWard();
    expect(theirs.abstained.map((a) => a.id)).not.toContain(row.id);
  });

  it.each(["19/10", "120/09", "20/80", "120/130", "301/80", "400/80", "300/201", "12/8", "abc"])(
    "an implausible or malformed admission blood pressure (%s) is rejected, never clamped",
    async (initialBp) => {
      signIn("rn-delacruz");
      const before = (await provider.getWard()).abstained.length;
      expect((await attempt(() => provider.admitPatient(admission({ initialBp })))).ok).toBe(false);
      expect((await provider.getWard()).abstained).toHaveLength(before);
    },
  );

  it.each(["20/10", "45/20", "300/200"])(
    "a critical but possible admission blood pressure (%s) is accepted as typed",
    async (initialBp) => {
      signIn("rn-delacruz");
      const before = (await provider.getWard()).abstained.length;
      const row = await provider.admitPatient(admission({ initialBp }));
      expect(row.reason.length).toBeGreaterThan(0);
      expect((await provider.getWard()).abstained).toHaveLength(before + 1);
    },
  );
});

// The way out of NOT RANKED needs the arbiter, which only the API has (D4: the frontend never
// computes a score). Runs last so the earlier assertions see the dataset's original ward.
describe.skipIf(!API_URL)("http provider: nurse-recorded vitals", () => {
  it("recording the missing blood pressure ranks the patient at once; implausible is rejected", async () => {
    httpSignIn("rn-delacruz");
    const before = await httpProvider.getWard();
    expect(before.abstained.find((a) => a.id === "p-004")?.reason).toBe("Systolic BP missing");

    const rejected = await attempt(() =>
      httpProvider.recordVitals("p-004", { systolic: 20, diastolic: 80 }),
    );
    expect(rejected.ok).toBe(false);
    expect((await httpProvider.getWard()).abstained.map((a) => a.id)).toContain("p-004");

    // A true critical reading is recordable, not refused: it ranks and escalates.
    const critical = await httpProvider.recordVitals("p-004", { systolic: 45, diastolic: 20 });
    expect(critical.ranked).toBe(true);
    expect(critical.score).toBe(3);

    const recorded = await httpProvider.recordVitals("p-004", { systolic: 130, diastolic: 84 });
    expect(recorded.ranked).toBe(true);
    expect(recorded.rank).not.toBeNull();
    expect(recorded.score).not.toBeNull();
    expect(recorded.blood_pressure?.provenance.source).toBe("nurse");

    const after = await httpProvider.getWard();
    expect(after.ranked.map((r) => r.id)).toContain("p-004");
    expect(after.abstained.map((a) => a.id)).not.toContain("p-004");
    expect(await httpProvider.getPatient("p-004")).not.toBeNull();
  });

  it("the entry form's check agrees with the server on a grid around both bounds", async () => {
    httpSignIn("rn-delacruz");
    const { min: sMin, max: sMax } = SYSTOLIC_BOUNDS;
    const { min: dMin, max: dMax } = DIASTOLIC_BOUNDS;
    const pairs: [number, number][] = [
      [sMin, dMin], // both floors: accepted
      [sMin - 1, dMin],
      [sMin, dMin - 1],
      [sMax, dMax], // both ceilings: accepted
      [sMax + 1, dMax],
      [sMax, dMax + 1],
      [45, 20], // a true critical reading: accepted
      [120, 120], // diastolic not below systolic
      [80, 120],
      [0, 0], // zero is missing, never a reading
      [120, 0],
      [120.5, 80], // the server's integers are strict: a fraction is refused by both
      [120, 80.5],
      [130, 84], // an ordinary reading
    ];
    for (const [systolic, diastolic] of pairs) {
      const clientOk = check({
        ...EMPTY_DRAFT,
        systolic: String(systolic),
        diastolic: String(diastolic),
      }).ok;
      const serverOk = (await attempt(() => httpProvider.recordVitals("p-004", { systolic, diastolic }))).ok;
      expect(clientOk, `${systolic}/${diastolic}`).toBe(serverOk);
    }
  });

  it("the fixture provider cannot re-rank and says so", async () => {
    const failure = await attempt(() =>
      fixtureProvider.recordVitals("p-004", { systolic: 130, diastolic: 84 }),
    );
    expect(failure.ok).toBe(false);
  });
});

function httpSignIn(clinicianId: string): void {
  setAuthToken(clinicianId);
}
