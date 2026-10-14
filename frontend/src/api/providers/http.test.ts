import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, setAuthToken } from "../client";
import { httpProvider } from "./http";

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status === 404 ? "Not Found" : "Error",
    headers: { "Content-Type": "application/json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  setAuthToken(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setAuthToken(null);
});

describe("httpProvider.getPatient", () => {
  it("returns the patient on 200", async () => {
    fetchMock.mockResolvedValue(reply(200, { id: "p-001" }));
    await expect(httpProvider.getPatient("p-001")).resolves.toEqual({ id: "p-001" });
    expect(fetchMock.mock.calls[0][0]).toBe("/patients/p-001");
  });

  it("returns null on 404 (missing and not-yours look the same)", async () => {
    fetchMock.mockResolvedValue(reply(404, { detail: "Not found" }));
    await expect(httpProvider.getPatient("p-999")).resolves.toBeNull();
  });

  it.each([401, 403, 500])("rethrows %s as an ApiError", async (status) => {
    fetchMock.mockResolvedValue(reply(status, { detail: "no" }));
    const failure = await httpProvider.getPatient("p-001").catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(status);
  });
});

describe("httpProvider requests", () => {
  it("sends the bearer token the session set", async () => {
    setAuthToken("rn-manalo");
    fetchMock.mockResolvedValue(reply(200, { ranked: [], abstained: [] }));
    await httpProvider.getWard();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer rn-manalo");
    expect(fetchMock.mock.calls[0][0]).toBe("/wards/W4/rows");
  });

  it("sends no Authorization header without a session", async () => {
    fetchMock.mockResolvedValue(reply(200, []));
    await httpProvider.listAllPatients();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).has("Authorization")).toBe(false);
  });
});
