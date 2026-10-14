import { describe, expect, it } from "vitest";
import { formatBloodPressure } from "./format";

describe("formatBloodPressure", () => {
  it("writes systolic over diastolic", () => {
    expect(formatBloodPressure({ systolic: 88, diastolic: 52 })).toBe("88/52");
    expect(formatBloodPressure({ systolic: 224, diastolic: 118 })).toBe("224/118");
  });

  it("is never the default object stringification", () => {
    expect(formatBloodPressure({ systolic: 120, diastolic: 80 })).not.toContain("[object");
  });
});
