import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HomeScreen } from "../src/counter/HomeScreen";
import type { FloorBill, Session } from "../src/services/api";

afterEach(() => (cleanup(), vi.restoreAllMocks()));

const session: Session = { token: "t", staff: { id: "s1", name: "Jane", role: "waiter" }, permissions: {}, auto_lock_seconds: 30 };
const order = (n: number, extra: Partial<FloorBill> = {}): FloorBill => ({
  id: `b${n}`, number: n, place: `Order #${String(n).padStart(4, "0")}`, section: "Bar", table_id: null, table_label: null,
  tab_name: null, waiter: { id: "s1", name: "Jane" }, mine: true, opened_at: new Date().toISOString(), total: 600,
  balance: 600, not_printed: false, ...extra,
});

describe("home: my open orders", () => {
  it("shows only my orders, finds one by number or table, and NEW ORDER opens one by number", async () => {
    const bills = [order(31), order(32, { table_label: "57", place: "Table 57" }), order(33, { mine: false, waiter: { id: "s2", name: "Ali" } })];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).endsWith("/floor")) return Response.json({ tables: [], bills });
      return Response.json({ id: "new", number: 34 }, { status: 201 });
    });
    const onOpen = vi.fn();
    const onPay = vi.fn();
    render(<HomeScreen session={session} onOpen={onOpen} onPay={onPay} onNavigate={vi.fn()} onLock={vi.fn()} />);
    expect(await screen.findByText("#0031")).toBeTruthy();
    expect(screen.getByText("No table")).toBeTruthy();
    expect(screen.queryByText("#0033")).toBeNull(); // Ali's order isn't on Jane's screen

    // A table that's leaving: straight to payment from the card.
    fireEvent.click(screen.getAllByRole("button", { name: /PAY 600/ })[0]);
    expect(onPay).toHaveBeenCalledWith("b32"); // newest first

    fireEvent.change(screen.getByPlaceholderText(/Find an order/), { target: { value: "57" } });
    expect(screen.queryByText("#0031")).toBeNull();
    expect(screen.getByText("#0032")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /NEW ORDER/ }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith("new"));
    const body = JSON.parse(String(fetchMock.mock.calls.find((c) => String(c[0]).endsWith("/bills"))![1]!.body));
    expect(body).toEqual({}); // no table, no name: just the next number
  });
});
