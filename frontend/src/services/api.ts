/** Talks to the Faida backend. The session token is kept in memory only, so closing or
 * reloading the screen always returns to the PIN pad. */

export type Role = "owner" | "supervisor" | "waiter";
export type Level = "allow" | "own" | "approval" | "deny";

export type Health = {
  mode: "local" | "cloud";
  version: string;
  set_up: boolean;
  business_name: string | null;
  cloud: "not_linked" | "off" | "online" | "offline"; // off: a counter-only install, by choice
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

export type SellOption = { id: string; label: string; price: number; offer_price: number | null; offer: string | null };
export type ModifierGroup = {
  id: string;
  name: string;
  min_select: number;
  max_select: number;
  options: { id: string; label: string; price: number }[];
};
export type MenuItem = {
  id: string;
  name: string;
  station: "bar" | "kitchen";
  favourite: boolean;
  available: boolean;
  image: string | null;
  is_combo: boolean;
  combo_parts: string[];
  modifier_groups: ModifierGroup[];
  options: SellOption[];
};
export type Menu = {
  categories: { id: string; name: string; items: MenuItem[] }[];
  note_presets: string[];
  happy_hours: { name: string; percent_off: number; until: string }[];
};

export type Person = { id: string; name: string };
export type FloorBill = {
  id: string;
  number: number;
  place: string;
  section: string;
  table_id: string | null;
  table_label: string | null;
  tab_name: string | null;
  waiter: Person;
  mine: boolean;
  opened_at: string;
  total: number | null;
  balance: number | null;
  not_printed: boolean | null;
};
export type TableRow = { id: string; name: string; section: string; sort_order: number; active: boolean };
export type Floor = { tables: TableRow[]; bills: FloorBill[] };

export type BillLine = {
  id: string;
  sell_option_id: string;
  item_name: string;
  option_label: string;
  station: "bar" | "kitchen";
  unit_price: number;
  note: string | null;
  sent_at: string;
  ticket_id: string;
  voided: boolean;
  void_reason: "not_prepared" | "already_prepared" | null;
  modifiers: { id: string; group: string; label: string; price: number }[];
  list_price: number | null;
  price_rule: string | null;
  comp_reason: CompReason | null;
  combo_parent_id: string | null;
};
export type CompReason = "house" | "staff_drink" | "owner_guest" | "complaint" | "promotion";
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
  method: "cash" | "mpesa" | "card";
  amount: number;
  tendered: number | null;
  tip: number;
  mpesa_ref: string | null;
  card_ref: string | null;
  created_at: string;
  taken_by: string;
  reversed: boolean;
};
export type Bill = {
  id: string;
  number: number;
  place: string;
  table_id: string | null;
  table_label: string | null;
  tab_name: string | null;
  section: string;
  waiter: Person;
  status: "open" | "paid" | "credit" | "unpaid_responsible" | "cancelled" | "merged";
  opened_at: string;
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
  business_day_cutoff: string;
  auto_lock_seconds: number;
  tot_size_ml: number | null;
  mpesa_code_entry: "last4" | "full" | "none";
  mpesa_till_number: string | null;
  receipt_footer: string;
  note_presets: string[];
  tab_section: string;
  report_emails: string[];
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

/** An order by its number ({}), or at a table: set up (table_id) or typed ("57", "S12"). */
export const openBill = (place: Record<string, never> | { table_id: string } | { table: string } | { tab_name: string } = {}) =>
  api<Bill>("/bills", { body: place });

export type RoundItem = { sell_option_id: string; quantity: number; note: string | null; modifier_option_ids: string[] };
export const sendRound = (billId: string, items: RoundItem[]) => api<Bill>(`/bills/${billId}/send`, { body: { items } });
export const printBill = (billId: string) => api<Bill>(`/bills/${billId}/print`, { method: "POST" });
export const voidLine = (billId: string, lineId: string, reason: string, approvalId?: string) =>
  api<Bill>(`/bills/${billId}/lines/${lineId}/void`, { body: { reason, approval_id: approvalId } });
export const moveBill = (billId: string, to: { table_id: string } | { table: string }) => api<Bill>(`/bills/${billId}/move`, { body: to });
export const handOver = (billId: string, toPin: string) => api<Bill>(`/bills/${billId}/handover`, { body: { to_pin: toPin } });
export const mergeBill = (billId: string, fromBillId: string) =>
  api<Bill>(`/bills/${billId}/merge`, { body: { from_bill_id: fromBillId } });
export const splitBill = (billId: string, lineIds: string[]) => api<Bill>(`/bills/${billId}/split`, { body: { line_ids: lineIds } });
export const closeEmpty = (billId: string) => api<Bill>(`/bills/${billId}/close-empty`, { method: "POST" });
export const reprint = (ticketId: string, approvalId?: string) =>
  api<Bill>(`/tickets/${ticketId}/reprint`, { body: { approval_id: approvalId } });

export type PaymentIn = {
  method: "cash" | "mpesa" | "card";
  amount: number;
  tendered?: number;
  tip?: number;
  mpesa_code?: string;
  card_ref?: string;
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
export const updateCustomer = (id: string, body: Partial<{ name: string; phone: string; credit_limit: number; active: boolean }>) =>
  api<CreditCustomer>(`/credit/customers/${id}`, { method: "PATCH", body });
export const putOnCredit = (billId: string, customerId: string, approvalId?: string) =>
  api<Bill>(`/bills/${billId}/credit`, { body: { customer_id: customerId, approval_id: approvalId } });
export const markUnpaid = (billId: string) => api<Bill>(`/bills/${billId}/unpaid`, { method: "POST" });
export const collectCredit = (customerId: string, body: { amount: number; method: "cash" | "mpesa"; mpesa_code?: string }) =>
  api<CreditCustomer>(`/credit/customers/${customerId}/collections`, { body });
export type CreditHistoryRow = { at: string; kind: "credit" | "paid"; what: string; amount: number; balance: number; by: string | null };
export const getCreditHistory = (customerId: string) => api<CreditHistoryRow[]>(`/credit/customers/${customerId}/history`);

// Shifts and cash-up
export type CashUp = {
  bills: number;
  total_sales: number;
  mpesa: number;
  card: number;
  credit: number;
  cash_taken_by_others: number;
  cash_due_from_sales: number;
  unpaid_responsible: number;
  cash_taken_for_others: number;
  float_amount: number;
  mpesa_tips: number;
  cash_to_hand_over: number;
  mpesa_payments: { bill_number: number; amount: number; tip: number; ref: string | null; at: string; method: "mpesa" | "card" }[];
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
  declared: { cash: number; mpesa: number; credit: number } | null;
  faida: { cash: number; mpesa: number; credit: number } | null;
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
  declared?: { cash: number; mpesa: number; credit: number };
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
  takings: { cash: number; mpesa: number; card: number; credit: number; unpaid: number; total: number; credit_paid_cash: number; credit_paid_mpesa: number } | null;
  payments: { at: string; what: string; method: "cash" | "mpesa" | "card" | "credit" | "credit_paid"; paid_by: "cash" | "mpesa" | "card" | null; amount: number; ref: string | null; by: string }[];
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
  selling: { option_id: string; name: string; price: number }[];
  buying_price: string | null;
  value: number | null;
};
export type StockMovement = { kind: string; quantity: string; text: string; note: string | null; by: string | null; at: string };
export type Variance = {
  stock_item_id: string;
  name: string;
  expected_text: string;
  counted_text: string;
  variance: string;
  message: string;
  value: number | null;
  since: string | null;
  opening_text: string | null;
  received_text: string;
  sold_text: string;
  waste_text: string;
};
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
export const stockTake = (note: string | undefined, counts: { stock_item_id: string; full: number; open_tenths: number; open_ml?: number }[]) =>
  api<{ id: string; lines: Variance[]; total_value: number | null }>("/stock/takes", { body: { note, counts } });
export const getRecipes = () => api<Recipe[]>("/stock/recipes");
export const setRecipe = (optionId: string, lines: RecipeLine[]) =>
  api<Recipe>(`/stock/recipes/${optionId}`, { method: "PUT", body: { lines } });

// Daily closing, reports, expenses
export type SalesSummary = { bills: number; total: number; cash: number; mpesa: number; card: number; credit: number; unpaid: number; discounts: number; tips: number; average_bill: number };
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
  comps: Comps;
  sections: { section: string; sales: number }[];
  unpaid_bills: { bill: number; place: string; waiter: string; amount: number }[];
  stock_variance: { day: string; item: string; variance: string; value: number | null }[];
  stock: { low: { item: string; level: string }[]; check: { item: string; level: string }[]; value: number | null };
  blockers: { open_shifts: string[]; open_bills: { bill: number; place: string; waiter: string }[] };
  profit?: Profit;
};
export type Comps = {
  items: { bill: number; item: string; reason: CompReason; value: number; asked_by: string | null; approved_by: string | null }[];
  total: number;
  by_reason: Record<string, number>;
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
    by_section: { section: string; sales: number }[];
    by_station: { station: string; sales: number }[];
    best: { item: string; quantity: number; sales: number }[];
    worst: { item: string; quantity: number; sales: number }[];
  };
  expenses: { by_category: Record<string, number>; total: number };
  shortages: { staff: string; shifts: number; times_short: number; short: number; times_over: number; over: number }[];
  variance: { day: string; item: string; variance: string; value: number | null }[];
  debtors: { name: string; phone: string | null; owed: number; limit: number; since: string | null }[];
  stock: { low: { item: string; level: string }[]; check: { item: string; level: string }[]; value: number | null };
  credit_collected: { cash: number; mpesa: number; total: number };
  comps: Comps;
};
export type PaidHow = "cash_box" | "cash" | "mpesa" | "bank";
export type Expense = {
  id: string;
  category: string;
  amount: number;
  note: string | null;
  business_day: string;
  from_cash_box: boolean;
  reversed: boolean;
  is_reversal: boolean;
  by: string;
  payee: string | null;
  paid_how: PaidHow | null;
  reference: string | null;
  quantity: string | null;
  unit_price: number | null;
};
export type MonthTotals = { month: string; total: number; by_category: Record<string, number> };

export const getClosing = (day?: string) => api<Closing>(`/closing${day ? `?day=${day}` : ""}`);
/** Owner printouts on the counter's receipt printer (80 mm). */
export type SlipKind = "closing" | "stock_sheet" | "debtors";
export const printSlip = (kind: SlipKind, day?: string) =>
  api<{ status: "printed" | "not_printed" | "pending" }>("/reports/slip", { body: { kind, day } });
export const closeDay = (day: string, cashBoxCounted?: number, note?: string) =>
  api<Closing>("/closing", { body: { day, cash_box_counted: cashBoxCounted, note } });
export type DashSummary = { sales: number; bills: number; average_bill: number };
export type Dashboard = {
  day: string;
  compare_day: string;
  cutoff_hour: number;
  now_slot: number;
  today: DashSummary & { items: number };
  last_week_so_far: DashSummary;
  last_week_total: number;
  by_hour: { today: number[]; last_week: number[] };
  payments: { cash: number; mpesa: number; card: number; credit: number; unpaid: number };
  best: { item: string; image: string | null; quantity: number; sales: number }[];
  by_category: { category: string; sales: number }[];
  by_waiter: { waiter: string; bills: number; sales: number }[];
  live: {
    open_bills: number;
    open_value: number;
    tables: number;
    tables_in_use: number;
    oldest_open: string | null;
    on_shift: { staff: string; since: string; role: Role }[];
  };
  alerts: { tone: "warn" | "bad"; text: string }[];
  recent: { number: number; place: string; waiter: string; total: number; closed_at: string; paid_by: string }[];
  gross_profit: { amount: number; margin: number | null } | null;
};
export const getDashboard = () => api<Dashboard>("/dashboard");

export const getReport = (start: string, end: string) => api<Report>(`/reports?start=${start}&end=${end}`);
export const getExpenses = (start: string, end: string) => api<Expense[]>(`/expenses?start=${start}&end=${end}`);
export const addExpense = (body: {
  category: string;
  amount?: number;
  note?: string;
  business_day?: string;
  payee?: string;
  paid_how: PaidHow;
  reference?: string;
  quantity?: number;
  unit_price?: number;
}) => api<Expense>("/expenses", { body });
export const getExpenseSummary = (month?: string) =>
  api<{ this_month: MonthTotals; last_month: MonthTotals }>(`/expenses/summary${month ? `?month=${month}` : ""}`);
export const reverseExpense = (id: string) => api<Expense>(`/expenses/${id}/reverse`, { method: "POST" });

// Selling extras
export const compLine = (billId: string, lineId: string, reason: CompReason, approvalId?: string) =>
  api<Bill>(`/bills/${billId}/lines/${lineId}/comp`, { body: { reason, approval_id: approvalId } });
export const setAvailability = (itemId: string, available: boolean) =>
  api<void>(`/menu/items/${itemId}/availability`, { body: { available } });

// Downloads (Excel) need the session, so they are fetched and saved from here.
export async function download(path: string, fallbackName: string) {
  const r = await fetch(`/api${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new ApiError(r.status, typeof data.detail === "string" ? data.detail : "Couldn't download it.");
  }
  const name = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

// Owner: menu, tables, staff, settings
export type ManageOption = { id: string; label: string; price: number; sort_order: number; active: boolean };
export type ManageItem = {
  id: string;
  category_id: string;
  name: string;
  station: "bar" | "kitchen";
  favourite: boolean;
  available: boolean;
  active: boolean;
  sort_order: number;
  image: string | null;
  is_combo: boolean;
  combo: { sell_option_id: string; quantity: number }[];
  modifier_group_ids: string[];
  options: ManageOption[];
};
export type ManageGroup = ModifierGroup & { active: boolean };
export type PriceRuleRow = {
  id: string;
  name: string;
  percent_off: number;
  days: number[];
  start_time: string;
  end_time: string;
  category_ids: string[];
  active: boolean;
};
export type ManageMenu = {
  categories: { id: string; name: string; sort_order: number; active: boolean }[];
  items: ManageItem[];
  modifier_groups: ManageGroup[];
  price_rules: PriceRuleRow[];
};
export const getManageMenu = () => api<ManageMenu>("/menu/manage");
export const createCategory = (name: string, sort_order = 0) => api<{ id: string }>("/menu/categories", { body: { name, sort_order } });
export const updateCategory = (id: string, body: Partial<{ name: string; sort_order: number; active: boolean }>) =>
  api<void>(`/menu/categories/${id}`, { method: "PATCH", body });
export const createItem = (body: {
  category_id: string;
  name: string;
  station: "bar" | "kitchen";
  favourite: boolean;
  options: { label: string; price: number }[];
}) => api<{ id: string }>("/menu/items", { body });
export const updateItem = (id: string, body: Partial<{ category_id: string; name: string; station: string; favourite: boolean; active: boolean; sort_order: number }>) =>
  api<void>(`/menu/items/${id}`, { method: "PATCH", body });
export const addOption = (itemId: string, body: { label: string; price: number }) => api<{ id: string }>(`/menu/items/${itemId}/options`, { body });
export const updateOption = (id: string, body: Partial<{ label: string; price: number; active: boolean }>) =>
  api<void>(`/menu/options/${id}`, { method: "PATCH", body });
export const setItemImage = (itemId: string, dataUrl: string) => api<{ image: string }>(`/menu/items/${itemId}/image`, { body: { data_url: dataUrl } });
export const removeItemImage = (itemId: string) => api<void>(`/menu/items/${itemId}/image`, { method: "DELETE" });
export const setItemGroups = (itemId: string, groupIds: string[]) =>
  api<void>(`/menu/items/${itemId}/modifier-groups`, { method: "PUT", body: { group_ids: groupIds } });
export const setCombo = (itemId: string, parts: { sell_option_id: string; quantity: number }[]) =>
  api<void>(`/menu/items/${itemId}/combo`, { method: "PUT", body: { parts } });
export const createGroup = (body: { name: string; min_select: number; max_select: number }) => api<{ id: string }>("/menu/modifier-groups", { body });
export const updateGroup = (id: string, body: Partial<{ name: string; min_select: number; max_select: number; active: boolean }>) =>
  api<void>(`/menu/modifier-groups/${id}`, { method: "PATCH", body });
export const addModOption = (groupId: string, body: { label: string; price: number; stock_item_id?: string | null; stock_quantity?: number | null }) =>
  api<{ id: string }>(`/menu/modifier-groups/${groupId}/options`, { body });
export const updateModOption = (id: string, body: Partial<{ label: string; price: number; active: boolean }>) =>
  api<void>(`/menu/modifier-options/${id}`, { method: "PATCH", body });
export const createRule = (body: Omit<PriceRuleRow, "id" | "active">) => api<{ id: string }>("/menu/price-rules", { body });
export const updateRule = (id: string, body: Partial<Omit<PriceRuleRow, "id">>) => api<void>(`/menu/price-rules/${id}`, { method: "PATCH", body });

export const createTable = (body: { name: string; section: string; sort_order?: number }) => api<TableRow>("/tables", { body });
export const updateTable = (id: string, body: Partial<{ name: string; section: string; active: boolean; sort_order: number }>) =>
  api<void>(`/tables/${id}`, { method: "PATCH", body });
export const getAllTables = () => getFloor().then((f) => f.tables);

export type StaffRow = { id: string; name: string; role: Role; active: boolean; created_at: string; deactivated_at: string | null };
export const getStaff = () => api<StaffRow[]>("/staff");
export const createStaff = (body: { name: string; role: Role; pin: string }) => api<StaffRow>("/staff", { body });
export const updateStaff = (id: string, body: Partial<{ name: string; role: Role }>) => api<StaffRow>(`/staff/${id}`, { method: "PATCH", body });
export const resetPin = (id: string, pin: string) => api<void>(`/staff/${id}/pin`, { body: { pin } });
export const deactivateStaff = (id: string) => api<StaffRow>(`/staff/${id}/deactivate`, { method: "POST" });

export const updateSettings = (body: Partial<Settings>) => api<Settings>("/settings", { method: "PATCH", body });
export const exitScreen = () => api<void>("/settings/exit-screen", { method: "POST" });

// Audit log (owner only): every void, discount, approval, price change...
export type AuditEntry = {
  id: string;
  created_at: string;
  action: string;
  by: string | null;
  entity_type: string | null;
  entity_id: string | null;
  approval_id: string | null;
  approved_by: string | null;
  reason: string | null;
  details: Record<string, unknown>;
};
export const getAudit = (opts: { before?: string; logins?: boolean } = {}) => {
  const q = new URLSearchParams({ limit: "100", logins: String(opts.logins ?? false) });
  if (opts.before) q.set("before", opts.before);
  return api<AuditEntry[]>(`/audit?${q}`);
};

// Salaries (owner)
export type PayType = "monthly" | "weekly" | "daily";
export type Employee = {
  id: string;
  name: string;
  job: string | null;
  phone: string | null;
  staff_id: string | null;
  staff_name: string | null;
  pay_type: PayType;
  pay_rate: number;
  active: boolean;
  balance: number;
  paid_to: string | null;
  shortages: { handover_id: string; day: string; amount: number }[];
};
export type PayEntry = {
  id: string;
  kind: "salary" | "advance" | "deduction" | "shortage" | "payment" | "reversal";
  amount: number;
  balance: number;
  note: string | null;
  business_day: string;
  period_start: string | null;
  period_end: string | null;
  reversed: boolean;
  by: string | null;
  at: string;
};
export type EmployeeIn = { name: string; job: string | null; phone: string | null; staff_id: string | null; pay_type: PayType; pay_rate: number };
export const getEmployees = () => api<Employee[]>("/payroll/employees");
export const addEmployee = (body: EmployeeIn) => api<Employee>("/payroll/employees", { body });
export const updateEmployee = (id: string, body: Partial<EmployeeIn & { active: boolean }>) =>
  api<Employee>(`/payroll/employees/${id}`, { method: "PATCH", body });
export const getPayEntries = (id: string) => api<PayEntry[]>(`/payroll/employees/${id}/entries`);
export const getDaysWorked = (id: string, start: string, end: string) =>
  api<{ days_worked: number | null }>(`/payroll/employees/${id}/days?start=${start}&end=${end}`);
export const giveAdvance = (id: string, body: { amount: number; paid_how: PaidHow; reference?: string; note?: string }) =>
  api<Employee>(`/payroll/employees/${id}/advances`, { body });
export const addDeduction = (id: string, body: { amount: number; note: string }) => api<Employee>(`/payroll/employees/${id}/deductions`, { body });
export const paySalary = (
  id: string,
  body: { period_start: string; period_end: string; earned: number; paid: number; paid_how: PaidHow; reference?: string; note?: string },
) => api<Employee>(`/payroll/employees/${id}/pay`, { body });
export const reversePayEntry = (entryId: string) => api<Employee>(`/payroll/entries/${entryId}/reverse`, { method: "POST" });
