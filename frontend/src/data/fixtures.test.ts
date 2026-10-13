// Invariants from README (I1-I7) and OVERVIEW.md checked against the fixture
// provider, so the CP3 generator and the CP6 HTTP provider inherit them.
//
// `it.fails` marks a KNOWN violation: the test passes while the invariant is
// broken and starts failing the moment it is fixed, so the marker must then be
// removed. Each one names the evidence and who closes it.

import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getPatient,
  getWard,
  listAllPatients,
  setActiveClinician,
} from "./fixtures";
import type {
  Provenance,
  ProvenanceSource,
  QualityLevel,
  ScoreRow,
  WardResponse,
} from "../types";

const SOURCES: readonly ProvenanceSource[] = [
  "device", "nurse", "lab", "derived", "model", "reference",
];
const QUALITY: readonly QualityLevel[] = ["ok", "degraded", "missing"];
// Nurse-entered vitals (CP1 added the structured BP and the NEWS2 oxygen inputs).
const NURSE_VITALS = new Set(["blood_pressure", "consciousness", "spo2_scale", "supplemental_o2"]);
// Ids of the sign-in profiles (src/pages/SignIn.tsx).
const CLINICIANS = ["rn-delacruz", "rn-reyes", "rn-manalo", "md-santos", "md-aquino"];

// Structural view of any generated *Measurement (number, string, boolean or BP object).
interface AnyMeasurement {
  readonly data: {
    readonly present: boolean;
    readonly value?: unknown;
    readonly reason?: string;
  };
  readonly provenance: Provenance;
}

interface Named {
  readonly path: string;
  readonly kind: "vital" | "lab";
  readonly key: string;
  readonly m: AnyMeasurement;
}

function measurements(row: ScoreRow): Named[] {
  const out: Named[] = [];
  for (const [key, m] of Object.entries(row.vitals)) {
    out.push({ path: `${row.id}.vitals.${key}`, kind: "vital", key, m });
  }
  for (const [key, m] of Object.entries(row.labs)) {
    if (m === null || typeof m === "number") continue; // absent lab, or freshness_hours
    out.push({ path: `${row.id}.labs.${key}`, kind: "lab", key, m });
  }
  return out;
}

function ids(w: WardResponse): string[] {
  return [...w.ranked, ...w.abstained].map((p) => p.id);
}

let ward: WardResponse;

beforeEach(async () => {
  setActiveClinician(null);
  ward = await getWard();
});

describe("ward shape", () => {
  it("has 10 ranked and 2 abstained patients, none in both lists", () => {
    expect(ward.ranked).toHaveLength(10);
    expect(ward.abstained).toHaveLength(2);
    expect(new Set(ids(ward)).size).toBe(12);
  });

  it("I3: the sort runs on Tier A, ranks are 1..n and scores never rise with rank", () => {
    expect(ward.sort_tier).toBe("A");
    ward.ranked.forEach((r, i) => {
      expect(r.sort_tier).toBe("A");
      expect(r.rank).toBe(i + 1);
      if (i > 0) expect(ward.ranked[i - 1].score).toBeGreaterThanOrEqual(r.score);
    });
  });
});

describe("I6 synthetic flag propagates", () => {
  it("every record and every measurement is synthetic", () => {
    for (const r of ward.ranked) {
      expect(r.synthetic, r.id).toBe(true);
      for (const { path, m } of measurements(r)) {
        expect(m.provenance.synthetic, path).toBe(true);
      }
    }
    for (const a of ward.abstained) expect(a.synthetic, a.id).toBe(true);
  });
});

describe("I1 missing is missing", () => {
  it("a missing measurement carries a reason; a present one is never a zero fill", () => {
    for (const r of ward.ranked) {
      for (const { path, m } of measurements(r)) {
        if (m.data.present) {
          const v = m.data.value;
          if (typeof v === "number") expect(v, path).toBeGreaterThan(0);
          else if (typeof v === "string") expect(v.length, path).toBeGreaterThan(0);
          else if (typeof v === "boolean") expect(v === true || v === false, path).toBe(true);
          else {
            expect(v, path).toBeTypeOf("object");
            for (const [k, n] of Object.entries(v as Record<string, unknown>)) {
              expect(typeof n, `${path}.${k}`).toBe("number");
              expect(n as number, `${path}.${k}`).toBeGreaterThan(0);
            }
          }
        } else {
          expect((m.data.reason ?? "").length, path).toBeGreaterThan(0);
        }
      }
    }
  });
});

describe("I2 every value carries provenance", () => {
  it("source, observed_at and quality are valid, and the source matches the origin", () => {
    for (const r of ward.ranked) {
      for (const { path, kind, key, m } of measurements(r)) {
        const p = m.provenance;
        expect(SOURCES, path).toContain(p.source);
        expect(QUALITY, path).toContain(p.quality);
        expect(Number.isNaN(Date.parse(p.observed_at)), `${path} observed_at`).toBe(false);
        const origin = kind === "lab" ? "lab" : NURSE_VITALS.has(key) ? "nurse" : "device";
        expect(p.source, path).toBe(origin);
      }
    }
  });
});

describe("I4 abstention is an output", () => {
  it("abstained rows carry a reason and an instruction, and no score or rank", () => {
    for (const a of ward.abstained) {
      expect(a.reason.length, a.id).toBeGreaterThan(0);
      expect(a.instruction.length, a.id).toBeGreaterThan(0);
      expect(Object.keys(a), a.id).not.toContain("score");
      expect(Object.keys(a), a.id).not.toContain("rank");
    }
  });

  it("an admitted patient starts NOT RANKED until the patch is applied", async () => {
    vi.resetModules(); // admitPatient mutates module state: use a fresh copy
    const fresh = await import("./fixtures");
    fresh.setActiveClinician(null);
    const row = await fresh.admitPatient({
      lastName: "Test", firstName: "Case", dateOfBirth: "1970-01-01", age: 55,
      sex: "F", bed: "9Z", admissionRoute: "direct_admission",
      chiefComplaint: "test", admittingContext: "test", attendingPhysician: "Dr Test",
    });
    const w = await fresh.getWard();
    expect(row.synthetic).toBe(true);
    expect(row.reason.length).toBeGreaterThan(0);
    expect(w.abstained.map((a) => a.id)).toContain(row.id);
    expect(w.ranked.map((r) => r.id)).not.toContain(row.id);
  });
});

describe("escalation arbiter output (fixtures stand in for it until CP4/CP5)", () => {
  const rows = () => ward.ranked.map((r) => ({
    id: r.id,
    score: r.score,
    tierA: r.escalation_reasons.filter((e) => e.rule === "tier_a_threshold"),
    tierB: r.escalation_reasons.filter((e) => e.rule === "tier_b_finding"),
  }));

  it("rule 1: every row at NEWS2 >= 5 has a tier_a_threshold reason", () => {
    for (const r of rows().filter((x) => x.score >= 5)) {
      expect(r.tierA.length, r.id).toBeGreaterThan(0);
    }
  });

  it("rule 3: a tier_b_finding reason names its pathway", () => {
    for (const r of rows()) {
      for (const e of r.tierB) expect(e.pathway ?? "", `${r.id} ${e.text}`).not.toBe("");
    }
  });

  it("a tier_a_threshold reason cites a score the row actually reached", () => {
    for (const r of rows()) {
      for (const e of r.tierA) {
        const m = /NEWS2\s*(≥|=)\s*(\d+)/.exec(e.text);
        expect(m, `${r.id} "${e.text}"`).not.toBeNull();
        const n = Number(m![2]);
        if (m![1] === "≥") expect(r.score, r.id).toBeGreaterThanOrEqual(n);
        else expect(r.score, r.id).toBe(n);
      }
    }
  });

  // KNOWN: p-007 "NEWS2 ≥ 4" (score 4) and p-008 "NEWS2 = 3" are filed under
  // tier_a_threshold, but RCP 2017 thresholds start at an aggregate of 5 (or a
  // single 3). Fixture scores also differ from NEWS2 of their own vitals in 9
  // of 10 rows. CP3 (generated data) and CP4 (news2) close this.
  it.fails("tier_a_threshold fires only at the RCP bands (aggregate >= 5)", () => {
    for (const r of rows()) {
      if (r.tierA.length > 0) expect(r.score, r.id).toBeGreaterThanOrEqual(5);
    }
  });
});

describe("Tier C stays isolated and display-only", () => {
  it("probability is calibrated into [0,1] and the model clock is its own", () => {
    for (const r of ward.ranked) {
      const c = r.tier_c;
      if (c === null) continue;
      expect(c.risk_probability, r.id).toBeGreaterThanOrEqual(0);
      expect(c.risk_probability, r.id).toBeLessThanOrEqual(1);
      expect(c.forecast_window.length, r.id).toBeGreaterThan(0);
      expect(Number.isInteger(c.scored_seconds_ago), r.id).toBe(true);
      expect(c.scored_seconds_ago, r.id).toBeGreaterThanOrEqual(0);
    }
  });

  it("attributions never name another tier's verdict (fuse inputs, never outputs)", () => {
    const verdict = /news2|kdigo|tier\s*[ab]\b|finding|escalat|priority/i;
    for (const r of ward.ranked) {
      for (const a of r.tier_c?.attributions ?? []) {
        expect(verdict.test(a.feature), `${r.id} "${a.feature}"`).toBe(false);
      }
    }
  });
});

describe("clinician scope (fixture stand-in for server-side filtering)", () => {
  for (const clinician of CLINICIANS) {
    it(`${clinician}: ward, list and detail agree and unassigned patients are unreachable`, async () => {
      setActiveClinician(null);
      const everyone = ids(await getWard());

      setActiveClinician(clinician);
      const w = await getWard();
      const visible = new Set(ids(w));
      const listed = new Set((await listAllPatients()).map((p) => p.id));

      expect(visible.size).toBeGreaterThan(0);
      expect(listed).toEqual(visible);
      expect(w.ranked.map((r) => r.rank)).toEqual(w.ranked.map((_, i) => i + 1));
      for (const id of everyone) {
        const detail = await getPatient(id);
        if (!visible.has(id)) expect(detail, `${clinician} -> ${id}`).toBeNull();
        else if (w.ranked.some((r) => r.id === id)) expect(detail, id).not.toBeNull();
      }
    });
  }

  // KNOWN: visiblePatientIds() returns null (no filter) for a clinician id with
  // no assignment entry, so an unknown id sees every patient. Access control
  // must fail closed (OVERVIEW.md "Ward view"; the server-side version needs
  // the same test). One-line fix in its own PR: return an empty Set.
  it.fails("an unknown clinician id sees no patients (fail closed)", async () => {
    setActiveClinician("not-a-clinician");
    const w = await getWard();
    expect(ids(w)).toHaveLength(0);
  });
});
