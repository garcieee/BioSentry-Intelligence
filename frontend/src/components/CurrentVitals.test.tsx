import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it } from "vitest";
import { getPatient, getWard, setActiveClinician } from "../data/fixtures";
import type { PatientDetail, Vitals } from "../types";
import { CurrentVitals, VitalRow } from "./CurrentVitals";
import { MeasurementDisplay } from "./MeasurementDisplay";

let patients: PatientDetail[];

beforeEach(async () => {
  setActiveClinician(null);
  const ward = await getWard();
  const loaded = await Promise.all(ward.ranked.map((r) => getPatient(r.id)));
  patients = loaded.filter((p): p is PatientDetail => p !== null);
});

const html = (vitals: Vitals) => renderToStaticMarkup(<CurrentVitals vitals={vitals} />);

describe("CURRENT VITALS", () => {
  it("writes blood pressure as systolic/diastolic", () => {
    const p001 = patients.find((p) => p.id === "p-001");
    expect(p001).toBeDefined();
    expect(html(p001!.vitals)).toContain("88/52");
  });

  it("never prints a stringified object, undefined or NaN for any patient", () => {
    expect(patients).toHaveLength(10);
    for (const p of patients) {
      const out = html(p.vitals);
      expect(out, p.id).not.toContain("[object Object]");
      expect(out, p.id).not.toContain("undefined");
      expect(out, p.id).not.toContain("NaN");
    }
  });

  it("shows a missing blood pressure as -- (not 0/0)", () => {
    const base = patients[0].vitals;
    const missing: Vitals = {
      ...base,
      blood_pressure: {
        data: { present: false, reason: "not_measured" },
        provenance: base.blood_pressure.provenance,
      },
    };
    const out = html(missing);
    expect(out).toContain("--");
    expect(out).not.toContain("0/0");
  });
});

describe("MeasurementDisplay", () => {
  const bp = (): Vitals["blood_pressure"] => patients[0].vitals.blood_pressure;

  it("refuses to stringify a structured value without a formatter", () => {
    // The type system already rejects this call; the runtime guard backs it up.
    // @ts-expect-error a structured value needs a format()
    const render = () => renderToStaticMarkup(<MeasurementDisplay measurement={bp()} />);
    expect(render).toThrow(/needs a format/);
  });

  it("accepts a structured value with a formatter", () => {
    const out = renderToStaticMarkup(
      <VitalRow
        label="Blood pressure"
        measurement={bp()}
        format={(v) => `${v.systolic}/${v.diastolic}`}
      />,
    );
    expect(out).toContain("/");
    expect(out).not.toContain("[object Object]");
  });
});
