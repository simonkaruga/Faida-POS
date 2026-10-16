import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PhoneApp } from "../src/owner-phone/PhoneApp";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

const today = {
  business_name: "Demo Bar",
  day: "2026-10-16",
  last_updated: new Date().toISOString(),
  sales: { bills: 3, total: 2050, cash: 1550, mpesa: 500, credit: 0, unpaid: 0, discounts: 0, tips: 0, average_bill: 683 },
  credit_collected: { total: 0 },
  shortages: [{ staff: "Jane", difference: -50 }],
  voids: { count: 0, total: 0 },
  low_stock: [],
  check_stock: [],
  open_shifts: [],
  closed: false,
  alerts: ["Jane short KSh 50"],
  dash: {
    day: "2026-10-16",
    compare_day: "2026-10-09",
    cutoff_hour: 6,
    now_slot: 14,
    today: { sales: 2050, bills: 3, average_bill: 683, items: 7 },
    last_week_so_far: { sales: 1640, bills: 2, average_bill: 820 },
    last_week_total: 4000,
    by_hour: { today: Array.from({ length: 24 }, (_, i) => (i === 14 ? 2050 : 0)), last_week: Array(24).fill(0) },
    payments: { cash: 1550, mpesa: 500, card: 0, credit: 0, unpaid: 0 },
    best: [{ item: "Tusker", image: null, quantity: 4, sales: 1200 }],
    by_category: [],
    by_waiter: [],
    live: { open_bills: 1, open_value: 300, tables: 10, tables_in_use: 1, oldest_open: null, on_shift: [] },
    alerts: [],
    recent: [],
    gross_profit: { amount: 900, margin: 44 },
  },
};

describe("owner phone", () => {
  it("logs in with email, password and code, then shows today", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      String(input).endsWith("/login") ? Response.json({ token: "t", business_name: "Demo Bar" }) : Response.json(today),
    );
    render(<PhoneApp />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "owner@demobar.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret password" } });
    fireEvent.change(screen.getByLabelText("Code from your authenticator app"), { target: { value: "12a3456" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByText("⚠ Jane short KSh 50")).toBeTruthy();
    expect(screen.getByText("2,050")).toBeTruthy();
    expect(screen.getByText("25% vs last Fri")).toBeTruthy(); // 2,050 against 1,640 by this time
    expect(screen.getByText(/Last updated/)).toBeTruthy();
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]!.body));
    expect(body).toEqual({ email: "owner@demobar.test", password: "secret password", code: "123456" });
    expect(fetchMock.mock.calls[1][1]!.headers).toEqual({ Authorization: "Bearer t" });
  });
});
