import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PinLogin } from "../src/counter/PinLogin";
import { formatKsh } from "../src/shared/money";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockFetch(status: number, body: unknown) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

const tap = (label: string) => fireEvent.click(screen.getByRole("button", { name: label }));

describe("PIN login", () => {
  it("sends the typed PIN and hands the session over", async () => {
    const session = { token: "t", staff: { id: "1", name: "Jane", role: "waiter" }, permissions: {}, auto_lock_seconds: 30 };
    const fetchMock = mockFetch(200, session);
    const onLogin = vi.fn();
    render(<PinLogin health={null} onLogin={onLogin} />);

    ["1", "3", "5", "7"].forEach(tap);
    expect(screen.getByLabelText("4 digits entered")).toBeTruthy();
    tap("OK");

    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(session));
    expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string)).toEqual({ pin: "1357" });
  });

  it("shows the backend's message and clears the PIN on a wrong PIN", async () => {
    mockFetch(401, { detail: "Wrong PIN." });
    render(<PinLogin health={null} onLogin={vi.fn()} />);
    ["9", "9", "9", "9"].forEach(tap);
    tap("OK");
    expect(await screen.findByText("Wrong PIN.")).toBeTruthy();
    expect(screen.getByLabelText("0 digits entered")).toBeTruthy();
  });

  it("deletes the last digit and stops at six digits", () => {
    render(<PinLogin health={null} onLogin={vi.fn()} />);
    ["1", "2", "3", "4", "5", "6", "7"].forEach(tap);
    expect(screen.getByLabelText("6 digits entered")).toBeTruthy();
    tap("Delete");
    expect(screen.getByLabelText("5 digits entered")).toBeTruthy();
  });
});

describe("formatKsh", () => {
  it("formats whole shillings with thousands separators", () => {
    expect(formatKsh(2100)).toBe("2,100");
    expect(formatKsh(8400.4)).toBe("8,400");
  });
});
