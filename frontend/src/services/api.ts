/** Talks to the Faida backend. The session token is kept in memory only, so closing or
 * reloading the screen always returns to the PIN pad. */

export type Role = "owner" | "supervisor" | "waiter";
export type Level = "allow" | "own" | "approval" | "deny";

export type Health = {
  mode: "local" | "cloud";
  version: string;
  set_up: boolean;
  business_name: string | null;
  cloud: "not_linked" | "online" | "offline";
  waiting_to_sync: number | null;
  last_synced_at: string | null;
  printers: "not_set_up" | "ok" | "offline";
};

export type Session = {
  token: string;
  staff: { id: string; name: string; role: Role };
  permissions: Record<string, Level>;
  auto_lock_seconds: number;
};

export type SellOption = { id: string; label: string; price: number };
export type MenuItem = { id: string; name: string; station: "bar" | "kitchen"; favourite: boolean; options: SellOption[] };
export type Menu = { categories: { id: string; name: string; items: MenuItem[] }[]; note_presets: string[] };

export type Person = { id: string; name: string };
export type FloorBill = {
  id: string;
  number: number;
  place: string;
  table_id: string | null;
  tab_name: string | null;
  waiter: Person;
  mine: boolean;
  total: number | null;
  balance: number | null;
  not_printed: boolean | null;
};
export type Floor = { tables: { id: string; name: string }[]; bills: FloorBill[] };

export type BillLine = {
  id: string;
  item_name: string;
  option_label: string;
  station: "bar" | "kitchen";
  unit_price: number;
  note: string | null;
  sent_at: string;
  ticket_id: string;
  voided: boolean;
  void_reason: "not_prepared" | "already_prepared" | null;
};
export type Ticket = {
  id: string;
  kind: "bar_slip" | "kitchen_ticket" | "bill" | "receipt";
  number: number;
  status: "pending" | "printed" | "not_printed";
  created_at: string;
  printed_at: string | null;
  reprints: number;
  last_error: string | null;
};
export type Payment = {
  id: string;
  method: "cash" | "mpesa";
  amount: number;
  tendered: number | null;
  tip: number;
  mpesa_ref: string | null;
  created_at: string;
  taken_by: string;
  reversed: boolean;
};
export type Bill = {
  id: string;
  number: number;
  place: string;
  table_id: string | null;
  tab_name: string | null;
  waiter: Person;
  status: "open" | "paid" | "credit" | "unpaid_responsible" | "cancelled" | "merged";
  lines: BillLine[];
  tickets: Ticket[];
  payments: Payment[];
  gross: number;
  discount: number;
  discount_kind: "amount" | "percent" | null;
  discount_value: number;
  total: number;
  paid: number;
  balance: number;
  tips: number;
  credit_customer: Person | null;
  credit_amount: number;
  cancel_reason: "not_prepared" | "already_prepared" | null;
};

export type Settings = {
  mpesa_code_entry: "last4" | "full" | "none";
  mpesa_till_number: string | null;
  note_presets: string[];
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public data?: Record<string, unknown>,
  ) {
    super(message);
  }
}

let token: string | null = null;
let onUnauthorized: () => void = () => {};

export function setToken(value: string | null) {
  token = value;
}

/** Called when the backend says the session has ended (idle, deactivated, restarted). */
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: init.method ?? (init.body ? "POST" : "GET"),
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: init.body ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "The counter is not responding. Check that Faida is running.");
  }
  if (response.status === 401 && token) onUnauthorized();
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      throw new ApiError(response.status, detail.message ?? "Something went wrong.", detail.code, detail);
    }
    if (Array.isArray(detail)) {
      // Validation error from the backend: show the first message.
      throw new ApiError(response.status, String(detail[0]?.msg ?? "Check what was entered.").replace(/^Value error, /, ""));
    }
    throw new ApiError(response.status, typeof detail === "string" ? detail : "Something went wrong.");
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export const login = (pin: string) => api<Session>("/auth/login", { body: { pin } });
export const lock = () => api<void>("/auth/lock", { method: "POST" });
export const getHealth = () => api<Health>("/health");
export const getSettings = () => api<Settings>("/settings");
export const getMenu = () => api<Menu>("/menu");
export const getFloor = () => api<Floor>("/floor");
export const getBill = (id: string) => api<Bill>(`/bills/${id}`);

export const openBill = (place: { table_id: string } | { tab_name: string }) => api<Bill>("/bills", { body: place });

export type RoundItem = { sell_option_id: string; quantity: number; note: string | null };
export const sendRound = (billId: string, items: RoundItem[]) => api<Bill>(`/bills/${billId}/send`, { body: { items } });
export const printBill = (billId: string) => api<Bill>(`/bills/${billId}/print`, { method: "POST" });
export const voidLine = (billId: string, lineId: string, reason: string, approvalId?: string) =>
  api<Bill>(`/bills/${billId}/lines/${lineId}/void`, { body: { reason, approval_id: approvalId } });
export const moveBill = (billId: string, tableId: string) => api<Bill>(`/bills/${billId}/move`, { body: { table_id: tableId } });
export const handOver = (billId: string, toPin: string) => api<Bill>(`/bills/${billId}/handover`, { body: { to_pin: toPin } });
export const mergeBill = (billId: string, fromBillId: string) =>
  api<Bill>(`/bills/${billId}/merge`, { body: { from_bill_id: fromBillId } });
export const splitBill = (billId: string, lineIds: string[]) => api<Bill>(`/bills/${billId}/split`, { body: { line_ids: lineIds } });
export const closeEmpty = (billId: string) => api<Bill>(`/bills/${billId}/close-empty`, { method: "POST" });
export const reprint = (ticketId: string, approvalId?: string) =>
  api<Bill>(`/tickets/${ticketId}/reprint`, { body: { approval_id: approvalId } });

export type PaymentIn = {
  method: "cash" | "mpesa";
  amount: number;
  tendered?: number;
  tip?: number;
  mpesa_code?: string;
  approval_id?: string;
  confirm_duplicate?: boolean;
};
export const takePayment = (billId: string, body: PaymentIn) =>
  api<{ bill: Bill; change: number }>(`/bills/${billId}/payments`, { body });

export const requestApproval = (action: string, approverPin: string, reason: string, decision: "approved" | "rejected") =>
  api<{ id: string; decision: string; approved_by: Person }>("/auth/approvals", {
    body: { action, approver_pin: approverPin, reason, decision },
  });

export const discountBill = (billId: string, kind: "amount" | "percent", value: number, reason: string, approvalId?: string) =>
  api<Bill>(`/bills/${billId}/discount`, { body: { kind, value, reason, approval_id: approvalId } });
export const cancelPaidBill = (billId: string, reason: string, approvalId?: string) =>
  api<Bill>(`/bills/${billId}/cancel`, { body: { reason, approval_id: approvalId } });

export type FinishedBill = {
  id: string;
  number: number;
  place: string;
  waiter: Person;
  status: Bill["status"];
  total: number;
  closed_at: string | null;
};
export const getFinishedBills = () => api<FinishedBill[]>("/bills");

// Credit
export type CreditCustomer = {
  id: string;
  name: string;
  phone: string | null;
  credit_limit: number;
  owed: number;
  available: number;
  oldest_unpaid: string | null;
};
export const getCustomers = () => api<CreditCustomer[]>("/credit/customers");
export const getDebtors = () => api<CreditCustomer[]>("/credit/debtors");
export const createCustomer = (body: { name: string; phone: string | null; credit_limit: number }) =>
  api<CreditCustomer>("/credit/customers", { body });
export const putOnCredit = (billId: string, customerId: string, approvalId?: string) =>
  api<Bill>(`/bills/${billId}/credit`, { body: { customer_id: customerId, approval_id: approvalId } });
export const markUnpaid = (billId: string) => api<Bill>(`/bills/${billId}/unpaid`, { method: "POST" });
export const collectCredit = (customerId: string, body: { amount: number; method: "cash" | "mpesa"; mpesa_code?: string }) =>
  api<CreditCustomer>(`/credit/customers/${customerId}/collections`, { body });

// Shifts and cash-up
export type CashUp = {
  bills: number;
  total_sales: number;
  mpesa: number;
  credit: number;
  cash_taken_by_others: number;
  cash_due_from_sales: number;
  unpaid_responsible: number;
  cash_taken_for_others: number;
  float_amount: number;
  mpesa_tips: number;
  cash_to_hand_over: number;
  mpesa_payments: { bill_number: number; amount: number; tip: number; ref: string | null; at: string }[];
};
export type ShiftInfo = { id: string; staff: Person; business_day: string; started_at: string; float_amount: number };
export type MyShift = {
  shift: ShiftInfo | null;
  cash_up: CashUp | null;
  open_bills: { id: string; number: number; place: string; balance: number }[];
};
export type Handover = {
  id: string;
  shift_id: string;
  staff: Person;
  receiver: Person;
  expected: number;
  received: number;
  difference: number;
  staff_agrees: boolean | null;
  staff_note: string | null;
  receiver_note: string | null;
  forced: boolean;
  created_at: string;
  shortage_status: "paid_back" | "deducted" | "forgiven" | null;
  printed: boolean;
};
export type ShiftRow = {
  shift: ShiftInfo;
  status: "open" | "closed";
  ended_at: string | null;
  open_bills: number;
  expected: number;
  handover: Handover | null;
};
export type CloseShift = {
  receiver_pin: string;
  counted_notes?: Record<string, number>;
  received?: number;
  receiver_note?: string;
  staff_pin: string;
  agree: boolean;
  staff_note?: string;
};
export const getMyShift = () => api<MyShift>("/shifts/me");
export const checkReceiver = (shiftId: string, pin: string) =>
  api<{ receiver: Person; cash_up: CashUp }>(`/shifts/${shiftId}/receiver`, { body: { pin } });
export const closeShift = (shiftId: string, body: CloseShift) => api<Handover>(`/shifts/${shiftId}/close`, { body });
export const forceClose = (shiftId: string, received: number, note: string) =>
  api<Handover>(`/shifts/${shiftId}/force-close`, { body: { received, note } });
export const giveFloat = (staffId: string, amount: number) => api<ShiftInfo>("/shifts/float", { body: { staff_id: staffId, amount } });
export const getShifts = () => api<ShiftRow[]>("/shifts");
export const getAlerts = () => api<{ staff: Person; times: number; total_short: number; message: string }[]>("/shifts/alerts");
export const setShortageStatus = (handoverId: string, outcome: string, note?: string) =>
  api<Handover>(`/handovers/${handoverId}/shortage-status`, { body: { outcome, note } });
export const getActiveStaff = () => api<(Person & { role: Role })[]>("/staff/active");

// Counter cash box
export type CashBox = {
  expected: number;
  today: { id: string; kind: "handover" | "float" | "payout" | "credit_collected" | "owner"; amount: number; note: string | null; by: string; at: string }[];
};
export const getCashBox = () => api<CashBox>("/cashbox");
export const recordPayout = (amount: number, reason: string) => api<CashBox>("/payouts", { body: { amount, reason } });
export const ownerCash = (amount: number, note: string) => api<CashBox>("/cashbox/owner", { body: { amount, note } });

// Stock
export type StockUnit = "ml" | "bottle" | "g" | "piece";
export type StockItem = {
  id: string;
  name: string;
  station: "bar" | "kitchen";
  unit: StockUnit;
  counting_unit: string;
  bottle_size: number | null;
  pack_name: string | null;
  pack_size: number | null;
  level: string;
  level_text: string;
  reorder_level: string;
  low: boolean;
  check: boolean;
  active: boolean;
  buying_price: string | null;
  value: number | null;
};
export type StockMovement = { kind: string; quantity: string; text: string; note: string | null; by: string | null; at: string };
export type Variance = { stock_item_id: string; name: string; expected_text: string; counted_text: string; variance: string; message: string; value: number | null };
export type RecipeLine = { stock_item_id: string; quantity: string; in_tots: boolean; stock_item?: string; text?: string };
export type Recipe = { sell_option_id: string; item_name: string; option_label: string; station: "bar" | "kitchen"; lines: RecipeLine[] };
export type Supplier = { id: string; name: string; phone: string | null };

export const getStock = () => api<StockItem[]>("/stock");
export const getMovements = (itemId: string) => api<StockMovement[]>(`/stock/items/${itemId}/movements`);
export const createStockItem = (body: Record<string, unknown>) => api<StockItem>("/stock/items", { body });
export const updateStockItem = (itemId: string, body: Record<string, unknown>) =>
  api<StockItem>(`/stock/items/${itemId}`, { method: "PATCH", body });
export const getSuppliers = () => api<Supplier[]>("/stock/suppliers");
export const addSupplier = (name: string, phone: string | null) => api<Supplier>("/stock/suppliers", { body: { name, phone } });
export const receiveDelivery = (body: {
  supplier_id?: string;
  note?: string;
  lines: { stock_item_id: string; packs: number; units: number; cost?: number }[];
}) => api<{ id: string; lines: string[] }>("/stock/deliveries", { body });
export const recordWaste = (body: { stock_item_id: string; quantity: number; tots: number; reason: string; approval_id?: string }) =>
  api<StockItem>("/stock/waste", { body });
export const stockTake = (note: string | undefined, counts: { stock_item_id: string; full: number; open_tenths: number }[]) =>
  api<{ id: string; lines: Variance[]; total_value: number | null }>("/stock/takes", { body: { note, counts } });
export const getRecipes = () => api<Recipe[]>("/stock/recipes");
export const setRecipe = (optionId: string, lines: RecipeLine[]) =>
  api<Recipe>(`/stock/recipes/${optionId}`, { method: "PUT", body: { lines } });

// Daily closing, reports, expenses
export type SalesSummary = { bills: number; total: number; cash: number; mpesa: number; credit: number; unpaid: number; discounts: number; tips: number; average_bill: number };
export type Profit = { sales: number; cost_of_sales: number; gross_profit: number; waste: number; variance: number; expenses: number; expenses_by_category: Record<string, number>; real_profit: number };
export type WaiterHandover = { staff: string; day: string; expected: number; received: number; difference: number; receiver: string; agrees: boolean | null; forced: boolean; shortage_status: string | null };
export type ClosingReport = {
  day: string;
  sales: SalesSummary;
  credit_collected: { cash: number; mpesa: number; total: number };
  cash_box: { expected_now: number; today: Record<string, number>; payouts: { amount: number; note: string | null; by: string }[] };
  waiters: WaiterHandover[];
  shortages: WaiterHandover[];
  overs: WaiterHandover[];
  voids: { bill: number; item: string; price: number; reason: string; asked_by: string | null; approved_by: string | null }[];
  void_total: number;
  discounts: { bill: number; amount: number; reason: string | null; asked_by: string | null; approved_by: string | null }[];
  discount_total: number;
  cancelled: { bill: number; total: number | null; reason: string; asked_by: string | null; approved_by: string | null }[];
  unpaid_bills: { bill: number; place: string; waiter: string; amount: number }[];
  stock_variance: { day: string; item: string; variance: string; value: number | null }[];
  stock: { low: { item: string; level: string }[]; check: { item: string; level: string }[]; value: number | null };
  blockers: { open_shifts: string[]; open_bills: { bill: number; place: string; waiter: string }[] };
  profit?: Profit;
};
export type Closing = { day: string; closed: boolean; closed_by: string | null; closed_at: string | null; cash_box_counted: number | null; note: string | null; report: ClosingReport };
export type Report = {
  start: string;
  end: string;
  sales: SalesSummary;
  profit: Profit;
  breakdown: {
    by_item: { item: string; quantity: number; sales: number }[];
    by_category: { category: string; sales: number }[];
    by_waiter: { waiter: string; bills: number; sales: number }[];
    by_hour: { hour: number; sales: number }[];
    best: { item: string; quantity: number; sales: number }[];
    worst: { item: string; quantity: number; sales: number }[];
  };
  expenses: { by_category: Record<string, number>; total: number };
  shortages: { staff: string; shifts: number; times_short: number; short: number; times_over: number; over: number }[];
  variance: { day: string; item: string; variance: string; value: number | null }[];
  debtors: { name: string; phone: string | null; owed: number; limit: number; since: string | null }[];
  stock: { low: { item: string; level: string }[]; check: { item: string; level: string }[]; value: number | null };
  credit_collected: { cash: number; mpesa: number; total: number };
};
export type Expense = { id: string; category: string; amount: number; note: string | null; business_day: string; from_cash_box: boolean; reversed: boolean; is_reversal: boolean; by: string };

export const getClosing = (day?: string) => api<Closing>(`/closing${day ? `?day=${day}` : ""}`);
export const closeDay = (day: string, cashBoxCounted?: number, note?: string) =>
  api<Closing>("/closing", { body: { day, cash_box_counted: cashBoxCounted, note } });
export const getReport = (start: string, end: string) => api<Report>(`/reports?start=${start}&end=${end}`);
export const getExpenses = (start: string, end: string) => api<Expense[]>(`/expenses?start=${start}&end=${end}`);
export const addExpense = (body: { category: string; amount: number; note?: string; from_cash_box: boolean }) =>
  api<Expense>("/expenses", { body });
export const reverseExpense = (id: string) => api<Expense>(`/expenses/${id}/reverse`, { method: "POST" });
