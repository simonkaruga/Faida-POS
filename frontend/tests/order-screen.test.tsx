import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OrderScreen } from "../src/counter/OrderScreen";
import type { Bill, FloorBill, Menu, Session } from "../src/services/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const session: Session = {
  token: "t",
  staff: { id: "s1", name: "Jane", role: "waiter" },
  permissions: { void_item: "approval" },
  auto_lock_seconds: 30,
};

const menu: Menu = {
  categories: [
    {
      id: "beer",
      name: "Beers",
      items: [
        {
          id: "tusker",
          name: "Tusker",
          station: "bar",
          favourite: true,
          available: true,
          image: null,
          is_combo: false,
          combo_parts: [],
          options: [{ id: "o-tusker", label: "", price: 300, offer_price: null, offer: null }],
          modifier_groups: [],
        },
      ],
    },
  ],
  note_presets: [],
  happy_hours: [],
};

const empty: Bill = {
  id: "b35", number: 35, place: "Order #0035", table_id: null, table_label: null, tab_name: null, section: "Bar",
  waiter: { id: "s1", name: "Jane" }, status: "open", opened_at: new Date().toISOString(), lines: [], tickets: [],
  payments: [], gross: 0, discount: 0, discount_kind: null, discount_value: 0, total: 0, paid: 0, balance: 0, tips: 0,
  credit_customer: null, credit_amount: 0, cancel_reason: null,
};

const order = (over: Partial<FloorBill>): FloorBill => ({
  id: "x", number: 1, place: "Order #0001", section: "Bar", table_id: null, table_label: null, tab_name: null,
  waiter: { id: "s1", name: "Jane" }, mine: true, opened_at: new Date().toISOString(), total: 600, balance: 600,
  not_printed: false, ...over,
});

function mockApi() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/floor"))
      return Response.json({
        tables: [],
        bills: [
          order({ id: "b31", number: 31, table_label: "5", place: "Table 5", balance: 1200 }),
          order({ id: "b33", number: 33, mine: false }),
          order({ id: "b35", number: 35 }),
        ],
      });
    if (url.endsWith("/send")) return Response.json({ ...empty, place: "Order #0035" });
    return Response.json(empty);
  });
}

const renderOrder = (props: Partial<Parameters<typeof OrderScreen>[0]> = {}) =>
  render(
    <OrderScreen
      session={session}
      menu={menu}
      billId="b35"
      onBack={vi.fn()}
      onPay={vi.fn()}
      onOpen={vi.fn()}
      onSent={vi.fn()}
      onMenuChanged={vi.fn()}
      {...props}
    />,
  );

describe("order screen: get in, tap items, SEND & PRINT", () => {
  it("shows my other orders one tap away, and sends with one big button", async () => {
    const fetchMock = mockApi();
    const onOpen = vi.fn();
    const onSent = vi.fn();
    renderOrder({ onOpen, onSent });

    // My other open order is above the bill; Ali's and this one aren't.
    const t5 = await screen.findByRole("button", { name: /T5/ });
    expect(screen.queryByRole("button", { name: /#33/ })).toBeNull();

    const tile = screen.getByRole("button", { name: /Tusker/ });
    fireEvent.click(tile);
    fireEvent.click(tile);
    expect(screen.getByText("2 item(s) to the bar / kitchen")).toBeTruthy();

    // Unsent items can't be left behind on the wrong order.
    fireEvent.click(t5);
    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toMatch(/Send the new items first/);

    fireEvent.click(screen.getByRole("button", { name: /SEND & PRINT/ }));
    await waitFor(() => expect(onSent).toHaveBeenCalled());
    const send = fetchMock.mock.calls.find((c) => String(c[0]).endsWith("/send"))!;
    expect(JSON.parse(String(send[1]!.body)).items).toEqual([{ sell_option_id: "o-tusker", quantity: 2, note: null, modifier_option_ids: [] }]);
  });

  it("switches to another of my orders when nothing is waiting to be sent", async () => {
    mockApi();
    const onOpen = vi.fn();
    renderOrder({ onOpen, billId: "b40" }); // unsent items are kept per order, in memory
    fireEvent.click(await screen.findByRole("button", { name: /T5/ }));
    expect(onOpen).toHaveBeenCalledWith("b31");
  });
});
