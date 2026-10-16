import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { groupLines } from "../src/counter/billLines";
import { addToDraft, draftTotal } from "../src/counter/drafts";
import { PayScreen } from "../src/counter/PayScreen";
import type { Bill, BillLine, Session } from "../src/services/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const line = (over: Partial<BillLine>): BillLine => ({
  id: Math.random().toString(),
  sell_option_id: "o1",
  item_name: "Tusker",
  option_label: "",
  station: "bar",
  unit_price: 300,
  note: null,
  sent_at: "",
  ticket_id: "t",
  voided: false,
  void_reason: null,
  modifiers: [],
  list_price: null,
  price_rule: null,
  comp_reason: null,
  combo_parent_id: null,
  ...over,
});

describe("building a round", () => {
  it("adds the same item up and keeps noted items separate", () => {
    const tusker = { optionId: "o1", name: "Tusker", price: 300, note: null, station: "bar" as const };
    let draft = addToDraft([], tusker);
    draft = addToDraft(draft, tusker);
    expect(draft).toHaveLength(1);
    expect(draft[0].quantity).toBe(2);
    draft = [{ ...draft[0], note: "cold" }];
    draft = addToDraft(draft, tusker);
    expect(draft).toHaveLength(2);
    expect(draftTotal(draft)).toBe(900);
  });

  it("groups sent lines and counts removed ones", () => {
    const groups = groupLines([
      line({}),
      line({}),
      line({ voided: true }),
      line({ item_name: "Johnnie Walker Red", option_label: "Single tot", unit_price: 250 }),
    ]);
    expect(groups.map((g) => [g.name, g.lines.length, g.voided])).toEqual([
      ["Tusker", 2, 1],
      ["Johnnie Walker Red - Single tot", 1, 0],
    ]);
  });
});

const session: Session = {
  token: "t",
  staff: { id: "s1", name: "Jane", role: "waiter" },
  permissions: { mpesa_duplicate_override: "approval" },
  auto_lock_seconds: 30,
};

const bill: Bill = {
  id: "b1",
  number: 142,
  place: "T2",
  table_id: "x",
  tab_name: null,
  section: "Main",
  waiter: { id: "s1", name: "Jane" },
  status: "open",
  opened_at: new Date().toISOString(),
  lines: [],
  tickets: [],
  payments: [],
  gross: 1250,
  discount: 0,
  discount_kind: null,
  discount_value: 0,
  total: 1250,
  paid: 0,
  balance: 1250,
  tips: 0,
  credit_customer: null,
  credit_amount: 0,
  cancel_reason: null,
};

function mockApi(onPayment: (body: Record<string, unknown>) => Response) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/settings")) return Response.json({ mpesa_code_entry: "last4", mpesa_till_number: null, note_presets: [] });
    if (url.endsWith("/payments")) return onPayment(JSON.parse(String(init!.body)));
    if (url.includes("/tickets/")) return Response.json({ id: "r", kind: "receipt", number: 142, status: "printed", reprints: 0, copies: [], content: [], last_error: null });
    return Response.json(bill);
  });
}

const tap = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

describe("pay screen", () => {
  it("shows change for cash and the PAID screen when the bill is settled", async () => {
    const paid = { ...bill, status: "paid", paid: 1250, balance: 0, tickets: [{ id: "r", kind: "receipt", status: "printed" }] };
    const fetchMock = mockApi(() => Response.json({ bill: paid, change: 750 }, { status: 201 }));
    render(<PayScreen session={session} billId="b1" onBack={vi.fn()} onDone={vi.fn()} />);
    await screen.findByText("TAKE CASH 1,250");
    tap("2,000");
    expect(screen.getByText("750")).toBeTruthy();
    tap("TAKE CASH 1,250");
    expect(await screen.findByText("PAID")).toBeTruthy();
    const body = JSON.parse(String(fetchMock.mock.calls.find((c) => String(c[0]).endsWith("/payments"))![1]!.body));
    expect(body).toEqual({ method: "cash", amount: 1250, tendered: 2000 });
  });

  it("warns about a repeated M-Pesa code and asks for approval", async () => {
    mockApi(() =>
      Response.json(
        { detail: { code: "mpesa_duplicate", message: "These characters were used on bill #0131. Check the customer's message.", bill_number: 131 } },
        { status: 409 },
      ),
    );
    render(<PayScreen session={session} billId="b1" onBack={vi.fn()} onDone={vi.fn()} />);
    await screen.findByText("TAKE CASH 1,250");
    tap("M-Pesa");
    ["P", "2", "Q", "M"].forEach(tap);
    tap("RECORD M-PESA 1,250");
    expect(await screen.findByText(/used on bill #0131/)).toBeTruthy();
    tap("GET APPROVAL");
    await waitFor(() => expect(screen.getByText("Approval needed")).toBeTruthy());
  });
});
