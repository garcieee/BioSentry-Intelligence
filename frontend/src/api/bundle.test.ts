/**
 * The bundle is part of the contract: an HTTP-mode build must carry neither the fixture
 * provider nor the synthetic dataset (patient names, vitals, notes). This builds the app both
 * ways with Vite's own build, in memory, and inspects the emitted chunks.
 *
 * Fails when: a static import of the fixture provider or `data/fixtures` is reintroduced on a
 * path that HTTP mode reaches, or the dataset is imported anywhere else in `src/`.
 */

import { fileURLToPath } from "node:url";
import { build } from "vite";
import { afterEach, describe, expect, it } from "vitest";
import synthetic from "../../../data/synthetic/synthetic.json";

const ROOT = fileURLToPath(new URL("../..", import.meta.url));

interface Emitted {
  readonly fileName: string;
  readonly isEntry: boolean;
  readonly code: string;
}

const original = process.env.VITE_API_URL;
afterEach(() => {
  if (original === undefined) delete process.env.VITE_API_URL;
  else process.env.VITE_API_URL = original;
});

async function bundle(apiUrl: string | undefined): Promise<Emitted[]> {
  if (apiUrl === undefined) delete process.env.VITE_API_URL;
  else process.env.VITE_API_URL = apiUrl;
  const result = await build({
    root: ROOT,
    logLevel: "silent",
    build: { write: false, minify: false, reportCompressedSize: false },
  });
  const outputs = Array.isArray(result) ? result : [result];
  const emitted: Emitted[] = [];
  for (const out of outputs) {
    if (!("output" in out)) throw new Error("expected a built bundle, not a watcher");
    for (const item of out.output) {
      if (item.type === "chunk") {
        emitted.push({ fileName: item.fileName, isEntry: item.isEntry, code: item.code });
      }
    }
  }
  return emitted;
}

// Full "Last, First" names: surnames alone collide with UI labels such as "Nurse Reyes".
const PATIENT_NAMES: string[] = [...synthetic.ranked, ...synthetic.abstained].map((p) => p.name);

const containing = (chunks: Emitted[], needle: string) =>
  chunks.filter((c) => c.code.includes(needle)).map((c) => c.fileName);

describe("the built bundle", () => {
  it("has a dataset to look for", () => {
    expect(PATIENT_NAMES.length).toBeGreaterThanOrEqual(12);
    expect(PATIENT_NAMES.every((n) => n.includes(", "))).toBe(true);
  });

  it("carries no fixture provider and no synthetic dataset in HTTP mode", async () => {
    const chunks = await bundle("http://127.0.0.1:8000");
    expect(chunks.length).toBeGreaterThan(0);
    for (const name of PATIENT_NAMES) {
      expect(containing(chunks, name), `patient "${name}" is in the HTTP-mode bundle`).toEqual([]);
    }
    expect(chunks.map((c) => c.fileName).filter((f) => /fixture/i.test(f))).toEqual([]);
    // The fixture provider's own strings are gone too, not only the data.
    expect(containing(chunks, "the frontend never computes a score")).toEqual([]);
    // The HTTP client is what is there instead.
    expect(containing(chunks, "/wards/W4/rows").length).toBeGreaterThan(0);
  }, 60_000);

  it("keeps the dataset out of the entry chunk in fixture mode (loaded on first use)", async () => {
    const chunks = await bundle(undefined);
    const entry = chunks.filter((c) => c.isEntry);
    const lazy = chunks.filter((c) => !c.isEntry);
    expect(entry.length).toBeGreaterThan(0);
    expect(lazy.length).toBeGreaterThan(0);
    for (const name of PATIENT_NAMES) {
      expect(containing(entry, name), `"${name}" is in the entry chunk`).toEqual([]);
      expect(containing(lazy, name).length, `"${name}" is in no lazy chunk`).toBeGreaterThan(0);
    }
  }, 60_000);
});
