import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AbstainedRow as AbstainedRowType } from "../types";
import { AbstainedRow } from "./AbstainedRow";

const row: AbstainedRowType = {
  id: "p-004",
  name: "Flores, Ramon",
  age: 73,
  sex: "M",
  bed: "4B",
  admitting_context: "Heart failure with preserved EF, admitted 2h ago",
  reason: "Systolic BP missing",
  instruction: "Record a blood pressure",
  synthetic: true,
};

describe("a NOT RANKED row", () => {
  it("states the reason and the instruction", () => {
    const out = renderToStaticMarkup(<AbstainedRow row={row} />);
    expect(out).toContain("Systolic BP missing");
    expect(out).toContain("Record a blood pressure");
    expect(out).toContain("NOT RANKED");
  });

  it("offers no entry unless the build can re-rank (fixture mode is unchanged)", () => {
    const out = renderToStaticMarkup(<AbstainedRow row={row} />);
    expect(out).not.toContain("Record vitals");
    expect(out).not.toContain("<button");
  });

  it("offers a collapsed 'Record vitals' action when it can", () => {
    const out = renderToStaticMarkup(
      <AbstainedRow row={row} canRecord clinicianId="rn-delacruz" />,
    );
    expect(out).toContain("Record vitals");
    expect(out).toContain('aria-expanded="false"');
    expect(out).not.toContain("<form"); // the form is opened by the nurse, not rendered up front
  });
});
