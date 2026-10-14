import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it } from "vitest";
import { getPatient, getWard, setActiveClinician } from "../data/fixtures";
import type { PatientDetail, Vitals } from "../types";
import { CurrentVitals, VitalRow } from "./CurrentVitals";
import { MeasurementDisplay } from "./MeasurementDisplay";

let patients: PatientDetail[];

beforeEach(async () => {
  setActiveClinician("rn-manalo");
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

  it("shows the two NEWS2 inputs the score depends on: oxygen and the SpO2 scale", () => {
    const base = patients[0].vitals;
    const recorded = (onOxygen: boolean, scale: 1 | 2): Vitals => ({
      ...base,
      supplemental_o2: {
        data: { present: true, value: onOxygen },
        provenance: base.supplemental_o2.provenance,
      },
      spo2_scale: {
        data: { present: true, value: scale },
        provenance: base.spo2_scale.provenance,
      },
    });
    const air = html(recorded(false, 1));
    expect(air).toContain("Room air");
    expect(air).toContain("Scale 1");
    const oxygen = html(recorded(true, 2));
    expect(oxygen).toContain("On oxygen");
    expect(oxygen).toContain("Scale 2");
    for (const out of [air, oxygen]) {
      expect(out).not.toMatch(/>(true|false)</);
    }
  });

  it("lists both rows for every patient, as -- when not recorded", () => {
    for (const p of patients) {
      const out = html(p.vitals);
      expect(out, p.id).toContain("Oxygen");
      expect(out, p.id).toContain("SpO2 scale");
      expect(out, p.id).not.toContain("undefined");
    }
  });

  it("shows an unrecorded oxygen status or SpO2 scale as --", () => {
    const base = patients[0].vitals;
    const unrecorded: Vitals = {
      ...base,
      supplemental_o2: {
        data: { present: false, reason: "not_recorded" },
        provenance: base.supplemental_o2.provenance,
      },
      spo2_scale: {
        data: { present: false, reason: "not_recorded" },
        provenance: base.spo2_scale.provenance,
      },
    };
    const out = html(unrecorded);
    expect(out).not.toContain("Scale ");
    expect(out).not.toContain("Room air");
    expect(out).not.toContain("On oxygen");
    expect(out).not.toContain("undefined");
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
