import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { VitalsEntryForm, type VitalsEntryFormProps } from "./VitalsEntry";
import { EMPTY_DRAFT } from "./vitalsDraft";

const base: VitalsEntryFormProps = {
  patientId: "p-004",
  patientName: "Flores, Ramon",
  clinicianId: "rn-delacruz",
  draft: EMPTY_DRAFT,
  problems: {},
  busy: false,
  failure: null,
  standingText: null,
  onChange: () => undefined,
  onSubmit: () => undefined,
  onClose: () => undefined,
};

const html = (over: Partial<VitalsEntryFormProps> = {}) =>
  renderToStaticMarkup(<VitalsEntryForm {...base} {...over} />);

describe("the vitals entry form", () => {
  it("offers the four NEWS2 inputs a nurse records, each with an explicit 'Not recorded'", () => {
    const out = html();
    for (const legend of ["Blood pressure (mmHg)", "Level of consciousness (ACVPU)", "Oxygen", "SpO2 scale"]) {
      expect(out).toContain(legend);
    }
    expect(out.match(/<span>Not recorded<\/span>/g)).toHaveLength(3);
    // Nothing is pre-selected except "Not recorded": no assumed oxygen status or scale.
    expect(out.match(/checked=""/g)).toHaveLength(3);
  });

  it("shows the bounds as placeholders and says nothing is filled in", () => {
    const out = html();
    expect(out).toContain('placeholder="20-300"');
    expect(out).toContain('placeholder="10-200"');
    expect(out).toContain("nothing");
    expect(out).toContain("Nothing to record yet.");
  });

  it("never prints undefined, NaN or a stringified object", () => {
    for (const out of [html(), html({ problems: { form: "Record at least one value." } })]) {
      expect(out).not.toContain("undefined");
      expect(out).not.toContain("NaN");
      expect(out).not.toContain("[object Object]");
    }
  });

  it("echoes what will be stored, and by whom, before anything is sent", () => {
    const out = html({
      draft: { ...EMPTY_DRAFT, systolic: "130", diastolic: "84", oxygen: "oxygen" },
    });
    expect(out).toContain("Will be recorded as a manual entry by rn-delacruz");
    expect(out).toContain("Blood pressure 130/84 mmHg");
    expect(out).toContain("Oxygen: on supplemental oxygen");
  });

  it("promises nothing while the draft cannot be sent", () => {
    const out = html({ draft: { ...EMPTY_DRAFT, systolic: "130" } });
    expect(out).toContain("Nothing to record yet.");
    expect(out).not.toContain("Will be recorded");
  });

  it("marks the fields at fault and says why", () => {
    const out = html({
      draft: { ...EMPTY_DRAFT, systolic: "5", diastolic: "80" },
      problems: { systolic: "Systolic must be 20 to 300." },
    });
    expect(out).toContain("Systolic must be 20 to 300.");
    expect(out).toContain('aria-invalid="true"');
  });

  it("shows the server's refusal as an alert and its answer as a status", () => {
    const failed = html({ failure: "Not recorded. systolic 19 is outside 20-300." });
    expect(failed).toContain('role="alert"');
    expect(failed).toContain("systolic 19 is outside 20-300");
    const answered = html({ standingText: "Ranked #3 with NEWS2 0." });
    expect(answered).toContain('role="status"');
    expect(answered).toContain("Ranked #3 with NEWS2 0.");
  });

  it("locks the form while a request is in flight", () => {
    const out = html({ busy: true });
    expect(out).toContain("Recording…");
    expect(out).toMatch(/<button type="submit"[^>]*disabled/);
    expect(out.match(/<fieldset[^>]*disabled/g)).toHaveLength(4);
  });
});
