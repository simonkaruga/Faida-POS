import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuditLog } from "../src/counter/AuditLog";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const entry = (over: Record<string, unknown>) => ({
  id: crypto.randomUUID(), created_at: "2026-10-28T19:20:00+03:00", entity_type: null, entity_id: null,
  approval_id: null, approved_by: null, reason: null, by: "Jane", details: {}, ...over,
});

describe("audit log", () => {
  it("shows who did what in plain words, with the approver, and can include logins", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      Response.json(String(input).includes("logins=true")
        ? [entry({ action: "staff.login" })]
        : [entry({ action: "bill_line.voided", approved_by: "Sam", reason: "customer changed mind",
                   details: { bill: 142, item: "Tusker", reason: "not_prepared" } }),
           entry({ action: "settings.updated", by: "Njeri", details: { tot_size_ml: [null, "25"] } })]),
    );
    render(<AuditLog />);
    expect(await screen.findByText("Item removed")).toBeTruthy();
    expect(screen.getByText("Item removed").className).toBe("warn");
    expect(screen.getByText(/bill #0142 · item Tusker · reason not_prepared/)).toBeTruthy();
    expect(screen.getByText("Sam")).toBeTruthy();
    expect(screen.getByText(/tot size ml — → 25/)).toBeTruthy();
    expect(String(fetchMock.mock.calls[0][0])).toContain("logins=false");

    fireEvent.click(screen.getByRole("button", { name: "With logins" }));
    expect(await screen.findByText("Logged in")).toBeTruthy();
  });
});
