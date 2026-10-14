// @vitest-environment jsdom
/**
 * The vitals-entry flow as a nurse drives it: typing, choosing, submitting. These run in a DOM
 * (jsdom + Testing Library); everything else in the suite stays on the node environment.
 *
 * The network is the API module, replaced here: what matters is what the form decides to send,
 * and what it shows for what comes back.
 */

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { getWard as fixtureWard, setActiveClinician } from "../data/fixtures";
import type { AbstainedRow as AbstainedRowType, NurseVitalsInput, Session, VitalsRecorded } from "../types";
import { AbstainedRow } from "./AbstainedRow";
import { VitalsEntry } from "./VitalsEntry";
import { Ward } from "../pages/Ward";

// React's act() environment is normally switched on by a global the runner does not provide.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({ recordVitals: vi.fn(), getWard: vi.fn() }));
vi.mock("../api", () => ({
  recordVitals: api.recordVitals,
  getWard: api.getWard,
  canRecordVitals: true,
}));

const ranked = (rank: number, score: number): VitalsRecorded => ({
  patient_id: "p-004",
  blood_pressure: null,
  consciousness: null,
  supplemental_o2: null,
  spo2_scale: null,
  ranked: true,
  rank,
  score,
  not_ranked_reason: null,
  not_ranked_instruction: null,
});

const stillNotRanked: VitalsRecorded = {
  ...ranked(1, 0),
  ranked: false,
  rank: null,
  score: null,
  not_ranked_reason: "No device data",
  not_ranked_instruction: "Apply the patch and verify the signal",
};

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

beforeEach(() => {
  api.recordVitals.mockReset();
  api.getWard.mockReset();
});
afterEach(cleanup);

const entry = (over: { onRecorded?: (r: VitalsRecorded) => void; onClose?: () => void } = {}) =>
  render(
    <VitalsEntry
      patientId="p-004"
      patientName="Flores, Ramon"
      clinicianId="rn-delacruz"
      onRecorded={over.onRecorded ?? (() => undefined)}
      onClose={over.onClose ?? (() => undefined)}
    />,
  );

const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
const recordButton = () => screen.getByRole("button", { name: "Record" });
const sentInput = (call = 0): NurseVitalsInput => api.recordVitals.mock.calls[call][1] as NurseVitalsInput;

describe("a draft that cannot be sent never reaches the network", () => {
  it("refuses a value outside the bounds and says why, in the form", async () => {
    const user = userEvent.setup();
    entry();
    await user.type(field("Systolic"), "400");
    await user.type(field("Diastolic"), "80");
    await user.click(recordButton());

    expect(api.recordVitals).not.toHaveBeenCalled();
    expect(screen.getByText("Systolic must be 20 to 300.")).toBeTruthy();
    expect(field("Systolic").getAttribute("aria-invalid")).toBe("true");
  });

  it("refuses diastolic not below systolic, half a pair, a fraction and an empty form", async () => {
    const user = userEvent.setup();
    entry();

    await user.type(field("Systolic"), "120");
    await user.type(field("Diastolic"), "120");
    await user.click(recordButton());
    expect(screen.getByText("Diastolic must be below systolic.")).toBeTruthy();

    await user.clear(field("Diastolic"));
    await user.click(recordButton());
    expect(screen.getByText("Enter the diastolic value.")).toBeTruthy();

    await user.clear(field("Systolic"));
    await user.type(field("Systolic"), "120.5");
    await user.type(field("Diastolic"), "80");
    await user.click(recordButton());
    expect(screen.getByText("Whole numbers only.")).toBeTruthy();

    await user.clear(field("Systolic"));
    await user.clear(field("Diastolic"));
    await user.click(recordButton());
    expect(screen.getByRole("alert").textContent).toBe("Record at least one value.");

    expect(api.recordVitals).not.toHaveBeenCalled();
  });

  it("clears the complaint as soon as the nurse changes the value", async () => {
    const user = userEvent.setup();
    entry();
    await user.type(field("Systolic"), "5");
    await user.type(field("Diastolic"), "80");
    await user.click(recordButton());
    expect(screen.queryByText("Systolic must be 20 to 300.")).not.toBeNull();

    await user.type(field("Systolic"), "0");
    expect(screen.queryByText("Systolic must be 20 to 300.")).toBeNull();
  });
});

describe("a valid draft is one request carrying only what was entered", () => {
  it("sends blood pressure and oxygen, nothing else, once", async () => {
    const user = userEvent.setup();
    const onRecorded = vi.fn();
    api.recordVitals.mockResolvedValue(ranked(5, 0));
    entry({ onRecorded });

    await user.type(field("Systolic"), "130");
    await user.type(field("Diastolic"), "84");
    await user.click(screen.getByLabelText("Room air"));
    // The echo says what will be stored, and by whom, before anything is sent.
    expect(screen.getByText("Will be recorded as a manual entry by rn-delacruz:")).toBeTruthy();
    expect(screen.getByText("Blood pressure 130/84 mmHg")).toBeTruthy();
    expect(screen.getByText("Oxygen: room air")).toBeTruthy();
    expect(api.recordVitals).not.toHaveBeenCalled();

    await user.click(recordButton());

    expect(api.recordVitals).toHaveBeenCalledTimes(1);
    expect(api.recordVitals.mock.calls[0][0]).toBe("p-004");
    // Exactly these keys: no acvpu, no spo2_scale, nothing null or defaulted. Room air is a
    // recorded false, not an omission.
    expect(sentInput()).toStrictEqual({ systolic: 130, diastolic: 84, on_oxygen: false });
    expect(await screen.findByText("Ranked #5 with NEWS2 0.")).toBeTruthy();
    expect(onRecorded).toHaveBeenCalledTimes(1);
    expect(onRecorded).toHaveBeenCalledWith(ranked(5, 0));
    // The form is ready for the next entry.
    expect(field("Systolic").value).toBe("");
  });

  it("sends a single choice alone", async () => {
    const user = userEvent.setup();
    api.recordVitals.mockResolvedValue(ranked(2, 3));
    entry();
    await user.click(screen.getByLabelText("U Unresponsive"));
    await user.click(recordButton());
    expect(sentInput()).toStrictEqual({ acvpu: "U" });

    await user.click(screen.getByLabelText("Scale 2"));
    await user.click(recordButton());
    expect(sentInput(1)).toStrictEqual({ spo2_scale: 2 });
    expect(api.recordVitals).toHaveBeenCalledTimes(2);
  });

  it("locks while the request is in flight, so a double click cannot send it twice", async () => {
    const user = userEvent.setup();
    let finish!: (value: VitalsRecorded) => void;
    api.recordVitals.mockReturnValue(
      new Promise<VitalsRecorded>((resolve) => {
        finish = resolve;
      }),
    );
    entry();
    await user.type(field("Systolic"), "130");
    await user.type(field("Diastolic"), "84");
    await user.click(recordButton());

    const busy = screen.getByRole("button", { name: "Recording…" }) as HTMLButtonElement;
    expect(busy.disabled).toBe(true);
    // Every group is locked, so the draft cannot change under the echo of a request in flight.
    // The fields sit in disabled fieldsets: disabled for the browser, whatever their own flag.
    const groups = screen.getAllByRole("group") as HTMLFieldSetElement[];
    expect(groups).toHaveLength(4);
    for (const group of groups) {
      expect(group.disabled, group.textContent ?? "").toBe(true);
    }
    const controls = [...screen.getAllByRole("radio"), field("Systolic"), field("Diastolic")];
    expect(controls.length).toBeGreaterThan(10);
    for (const control of controls) {
      expect(control.matches(":disabled")).toBe(true);
    }
    await user.click(busy);
    expect(api.recordVitals).toHaveBeenCalledTimes(1);

    finish(ranked(3, 0));
    expect(await screen.findByText("Ranked #3 with NEWS2 0.")).toBeTruthy();
    for (const control of [...screen.getAllByRole("radio"), field("Systolic"), field("Diastolic")]) {
      expect(control.matches(":disabled")).toBe(false);
    }
  });

  it("states why a patient is still not ranked, in the server's words", async () => {
    const user = userEvent.setup();
    api.recordVitals.mockResolvedValue(stillNotRanked);
    entry();
    await user.type(field("Systolic"), "118");
    await user.type(field("Diastolic"), "74");
    await user.click(recordButton());
    expect(
      await screen.findByText(
        "Still not ranked. No device data. Apply the patch and verify the signal.",
      ),
    ).toBeTruthy();
  });
});

describe("what the server refuses is shown as the server said it", () => {
  const reject = (status: number, body: unknown) =>
    api.recordVitals.mockRejectedValue(new ApiError(status, "refused", body));

  async function submitValid() {
    const user = userEvent.setup();
    await user.type(field("Systolic"), "130");
    await user.type(field("Diastolic"), "84");
    await user.click(recordButton());
  }

  it("shows a 422's reason by field and never echoes the rejected input", async () => {
    reject(422, {
      detail: [
        {
          type: "int_type",
          loc: ["body", "systolic"],
          msg: "Input should be a valid integer",
          input: "9187x",
        },
      ],
    });
    const onRecorded = vi.fn();
    entry({ onRecorded });
    await submitValid();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Not recorded. systolic: Input should be a valid integer.");
    expect(document.body.textContent).not.toContain("9187x");
    expect(onRecorded).not.toHaveBeenCalled();
    // The nurse's entry is kept, so it can be corrected rather than retyped.
    expect(field("Systolic").value).toBe("130");
    expect(field("Diastolic").value).toBe("84");
    expect((recordButton() as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows a plain-text reason from the server's own bounds", async () => {
    reject(422, { detail: "systolic 301 is outside 20-300" });
    entry();
    await submitValid();
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Not recorded. systolic 301 is outside 20-300.",
    );
  });

  it.each([
    [401, "You are not signed in. Sign in again, then record the values."],
    [403, "The server does not recognise this sign-in. Sign in again."],
    [404, "This patient is not on your list. Nothing was recorded."],
  ])("explains a %i", async (status, message) => {
    reject(status, { detail: "x" });
    entry();
    await submitValid();
    expect((await screen.findByRole("alert")).textContent).toBe(message);
  });

  it("does not claim nothing was stored when the network failed", async () => {
    api.recordVitals.mockRejectedValue(new TypeError("Failed to fetch"));
    entry();
    await submitValid();
    expect((await screen.findByRole("alert")).textContent).toContain("may not have been recorded");
  });
});

describe("the row and the ward page", () => {
  it("opens and closes the form from the row, collapsed until asked for", async () => {
    const user = userEvent.setup();
    render(<AbstainedRow row={row} canRecord clinicianId="rn-delacruz" />);
    expect(screen.queryByRole("form")).toBeNull();

    const toggle = screen.getByRole("button", { name: "Record vitals" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await user.click(toggle);
    expect(screen.getByRole("form", { name: "Record vitals for Flores, Ramon" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Close" })[0].getAttribute("aria-expanded")).toBe("true");

    await user.click(screen.getAllByRole("button", { name: "Close" })[0]);
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("fetches the ward again after a record and says where the patient now stands", async () => {
    const user = userEvent.setup();
    setActiveClinician("rn-delacruz");
    const before = await fixtureWard();
    expect(before.abstained.length).toBeGreaterThan(0);
    const target = before.abstained[0];
    api.getWard.mockResolvedValueOnce(before).mockResolvedValue({ ...before, abstained: [] });
    api.recordVitals.mockResolvedValue({ ...ranked(5, 0), patient_id: target.id });

    const session: Session = { clinician_id: "rn-delacruz", ward: before.ward, role: "rn" };
    render(
      <MemoryRouter>
        <Ward session={session} onSignOut={() => undefined} />
      </MemoryRouter>,
    );

    expect(await screen.findByText(new RegExp(`Not ranked \\(${before.abstained.length}\\)`))).toBeTruthy();
    await user.click(screen.getAllByRole("button", { name: "Record vitals" })[0]);
    await user.type(field("Systolic"), "130");
    await user.type(field("Diastolic"), "84");
    await user.click(recordButton());

    expect(await screen.findByText(`Recorded for ${target.name}. Ranked #5 with NEWS2 0.`)).toBeTruthy();
    expect(api.getWard).toHaveBeenCalledTimes(2); // the ranking on screen is the server's
    expect(screen.queryByText(/Not ranked \(/)).toBeNull();
  });
});
