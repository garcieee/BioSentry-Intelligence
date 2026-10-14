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

  it("I3: sorted on Tier A by escalation level, then NEWS2 total; ranks are 1..n", () => {
    expect(ward.sort_tier).toBe("A");
    const escalated = (r: WardResponse["ranked"][number]) =>
      r.escalation_reasons.some((e) => e.rule === "tier_a_threshold");
    ward.ranked.forEach((r, i) => {
      expect(r.sort_tier).toBe("A");
      expect(r.rank).toBe(i + 1);
      if (i === 0) return;
      const prev = ward.ranked[i - 1];
      // Escalated rows come first; within a group the total never rises with rank.
      expect(Number(escalated(prev)), r.id).toBeGreaterThanOrEqual(Number(escalated(r)));
      if (escalated(prev) === escalated(r)) {
        expect(prev.score, r.id).toBeGreaterThanOrEqual(r.score);
      }
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
          else if (typeof v === "boolean") continue;   // false (air) is a real value, never a fill
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

describe("escalation arbiter output (computed by the backend arbiter, not written)", () => {
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

  it("a tier_a_threshold reason cites the row's own total or a single-parameter trigger", () => {
    for (const r of rows()) {
      for (const e of r.tierA) {
        const total = /^Total (\d+) \(/.exec(e.text);
        if (total !== null) {
          expect(Number(total[1]), `${r.id} "${e.text}"`).toBe(r.score);
          expect(r.score, r.id).toBeGreaterThanOrEqual(5);
        } else {
          expect(e.text, `${r.id} "${e.text}"`).toMatch(/^Single parameter at 3: /);
        }
      }
    }
  });

  it("tier_a_threshold fires only at an RCP trigger (aggregate >= 5 or a single parameter at 3)", () => {
    for (const r of rows()) {
      if (r.tierA.length === 0) continue;
      const single = r.tierA.some((e) => e.text.startsWith("Single parameter at 3: "));
      expect(r.score >= 5 || single, r.id).toBe(true);
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

  // Fail closed: a clinician id with no assignment entry sees nobody, through the
  // ward, the list and the detail endpoint alike (OVERVIEW.md "Ward view"; the
  // server-side provider carries the same test).
  it("an unknown clinician id sees no patients (fail closed)", async () => {
    setActiveClinician(null);
    const everyone = ids(await getWard());
    setActiveClinician("not-a-clinician");
    const w = await getWard();
    expect(ids(w)).toHaveLength(0);
    expect(await listAllPatients()).toHaveLength(0);
    for (const id of everyone) expect(await getPatient(id), id).toBeNull();
  });
});
