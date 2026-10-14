import { afterEach, describe, expect, it, vi } from "vitest";

// Only the API can re-rank a patient (D4: the frontend never computes a score), so whether the
// build offers vitals entry is a property of how it was built: VITE_API_URL set or not.
afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function canRecordVitalsWith(apiUrl: string): Promise<boolean> {
  vi.stubEnv("VITE_API_URL", apiUrl);
  vi.resetModules();
  const api = await import("./index");
  return api.canRecordVitals;
}

describe("canRecordVitals", () => {
  it("is false in fixture mode: the fixture provider cannot re-rank and offers no entry", async () => {
    expect(await canRecordVitalsWith("")).toBe(false);
  });

  it("is true when the build is wired to an API", async () => {
    expect(await canRecordVitalsWith("http://127.0.0.1:8000")).toBe(true);
  });
});
