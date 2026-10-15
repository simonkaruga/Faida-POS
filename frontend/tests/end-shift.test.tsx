import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EndShift } from "../src/counter/EndShift";
import type { CashUp, Session } from "../src/services/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const session: Session = { token: "t", staff: { id: "j", name: "Jane", role: "waiter" }, permissions: {}, auto_lock_seconds: 30 };
const cash: CashUp = {
  bills: 3, total_sales: 18500, mpesa: 9200, credit: 1200, cash_taken_by_others: 0, cash_due_from_sales: 8100,
  unpaid_responsible: 0, cash_taken_for_others: 0, float_amount: 500, mpesa_tips: 200, cash_to_hand_over: 8400,
  mpesa_payments: [{ bill_number: 131, amount: 9200, tip: 200, ref: "P2QM", at: "2026-10-16T20:30:00Z" }],
};

describe("end my shift", () => {
  it("shows the cash-up, then counts notes against what is expected", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/receiver")) return Response.json({ receiver: { id: "o", name: "Njeri" }, cash_up: cash });
      return Response.json({ shift: { id: "s1", staff: { id: "j", name: "Jane" }, business_day: "2026-10-16", started_at: "", float_amount: 500 }, cash_up: cash, open_bills: [] });
    });
    render(<EndShift session={session} onPay={vi.fn()} onBack={vi.fn()} onDone={vi.fn()} />);
    expect(await screen.findByText("= CASH TO HAND OVER")).toBeTruthy();
    expect(screen.getByText("8,400")).toBeTruthy();

    const tap = (name: string) => fireEvent.click(screen.getByRole("button", { name }));
    tap("HAND OVER CASH");
    ["2", "5", "8", "0"].forEach(tap);
    tap("OK");
    await screen.findByText("Count Jane's cash");
    // 8 x 1,000, then 1 x 200, 1 x 100, 1 x 50 (NEXT moves down the list)
    tap("8");
    tap("NEXT");
    tap("NEXT");
    tap("1");
    tap("NEXT");
    tap("1");
    tap("NEXT");
    tap("1");
    expect(screen.getByText("SHORT 50")).toBeTruthy();
  });
});
