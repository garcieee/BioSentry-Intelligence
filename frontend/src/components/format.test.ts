import { describe, expect, it } from "vitest";
import { formatBloodPressure, formatOxygen, formatSpo2Scale } from "./format";

describe("formatBloodPressure", () => {
  it("writes systolic over diastolic", () => {
    expect(formatBloodPressure({ systolic: 88, diastolic: 52 })).toBe("88/52");
    expect(formatBloodPressure({ systolic: 224, diastolic: 118 })).toBe("224/118");
  });

  it("is never the default object stringification", () => {
    expect(formatBloodPressure({ systolic: 120, diastolic: 80 })).not.toContain("[object");
  });
});

describe("formatOxygen", () => {
  it("says room air or on oxygen, never true/false", () => {
    expect(formatOxygen(false)).toBe("Room air");
    expect(formatOxygen(true)).toBe("On oxygen");
  });
});

describe("formatSpo2Scale", () => {
  it("names the scale", () => {
    expect(formatSpo2Scale(1)).toBe("Scale 1");
    expect(formatSpo2Scale(2)).toBe("Scale 2");
  });
});
