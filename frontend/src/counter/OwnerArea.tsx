import {
  Armchair,
  ArrowLeft,
  ChevronDown,
  BookUser,
  CalendarCheck2,
  ChartColumn,
  HandCoins,
  LayoutDashboard,
  LogOut,
  Package,
  Phone,
  Pencil,
  Printer,
  ReceiptText,
  ScrollText,
  Settings2,
  SlidersHorizontal,
  TriangleAlert,
  Users,
  UtensilsCrossed,
  Vault,
  type LucideIcon,
  MonitorUp,
  Banknote,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import {
  api,
  ApiError,
  collectCredit,
  createCustomer,
  forceClose,
  getActiveStaff,
  getAlerts,
  getCashBox,
  getCreditHistory,
  getCustomers,
  exitScreen,
  getHealth,
  getShifts,
  getSettings,
  giveFloat,
  ownerCash,
  recordPayout,
  updateCustomer,
  reprint,
  setShortageStatus,
  type CashBox,
  type CreditHistoryRow,
  type CreditCustomer,
  type Session,
  type ShiftRow,
  type SlipKind,
} from "../services/api";
import { SUPPORT_PHONE } from "../shared/Brand";
import { PrintPageButton, SlipButton } from "../shared/PrintButtons";
import { CodeKeypad } from "../shared/CodeKeypad";
import { Keypad } from "../shared/Keypad";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";
import { getPrintouts, KIND_NAME, ReceiptDialog, StatusPill, type Printout } from "../shared/Receipt";
import { AuditLog } from "./AuditLog";
import { FinishedBills } from "./FinishedBills";
import { Dashboard } from "./Dashboard";
import { ClosingTab, ExpensesTab, ReportsTab } from "./OwnerReports";
import { SalariesTab } from "./Salaries";
import { ChoicesEditor, MenuEditor, SettingsEditor, StaffEditor, TablesEditor } from "./OwnerSetup";
import { StockTab } from "./StockTab";

type Tab =
  | "dashboard"
  | "shifts" | "credit" | "cash" | "stock" | "bills" | "printers" | "closing" | "reports" | "expenses" | "salaries" | "audit"
  | "menu" | "choices" | "tables" | "staff" | "settings";
const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");
const time = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "");
const KIND = { handover: "Hand-over", float: "Float", payout: "Pay-out", credit_collected: "Credit paid", owner: "Owner" } as const;

/** `print`: the page can be printed on A4 or saved as a PDF from its title bar.
 * `slip`: a short version prints on the receipt printer. */
type NavItem = { tab: Tab; label: string; icon: LucideIcon; hint: string; print?: true; slip?: { kind: SlipKind; label: string } };

/** Owner-panel text size, kept on this screen only. Large by default: it's read standing
 * at the counter. */
const TEXT_SIZES = [["normal", "A", 1], ["large", "A", 1.15], ["xl", "A", 1.3]] as const;
type TextSize = (typeof TEXT_SIZES)[number][0];
function savedTextSize(): TextSize {
  try {
    const v = localStorage.getItem("faida-owner-text");
    return v === "normal" || v === "xl" ? v : "large";
  } catch {
    return "large";
  }
}

/** Counter screens behind an Owner or Supervisor PIN (masterplan 9.4). Supervisors see
 * the same screens without owner-only pages and actions. */
export function OwnerArea({ session, onBack, onLock }: { session: Session; onBack: () => void; onLock: () => void }) {
  const [tab, setTab] = useState<Tab>("dashboard");
  // Setup is mostly used at installation: folded away until opened.
  const [setupOpen, setSetupOpen] = useState(false);
  const [textSize, setTextSize] = useState<TextSize>(savedTextSize);
  const [business, setBusiness] = useState("");
  useEffect(() => {
    getHealth().then((h) => setBusiness(h.business_name ?? ""), () => {});
  }, []);
  const chooseSize = (size: TextSize) => {
    setTextSize(size);
    try {
      localStorage.setItem("faida-owner-text", size);
    } catch {
      // only for this visit
    }
  };
  const isOwner = session.permissions.view_financials === "allow";
  const [exiting, setExiting] = useState<null | "ask" | "closing">(null);
  // Only the Windows counter has the kiosk task that closes the window.
  const canExit = session.permissions.manage_business === "allow" && navigator.userAgent.includes("Windows");
  const groups: [string, NavItem[]][] = [
    ["Today", [
      { tab: "dashboard", label: "Dashboard", icon: LayoutDashboard, hint: "Today at a glance", print: true, slip: { kind: "closing", label: "Today's slip" } },
      { tab: "shifts", label: "Shifts & hand-overs", icon: Users, hint: "Floats, cash-ups, shortages", print: true },
      { tab: "bills", label: "Finished orders", icon: ReceiptText, hint: "Today's receipts and cancellations", print: true },
      { tab: "cash", label: "Cash box", icon: Vault, hint: "Pay-outs and cash in the box", print: true },
      { tab: "printers", label: "Printer log", icon: Printer, hint: "Every slip, ticket and receipt" },
    ]],
    ["Business", [
      { tab: "credit", label: "Credit", icon: BookUser, hint: "Debtors and payments", print: true, slip: { kind: "debtors", label: "Debtors slip" } },
      { tab: "stock", label: "Stock", icon: Package, hint: "Deliveries, counts, waste", print: true, slip: { kind: "stock_sheet", label: "Count sheet" } },
      { tab: "closing", label: "Daily closing", icon: CalendarCheck2, hint: "End the business day" },
    ]],
    ...(isOwner
      ? ([["Owner", [
          { tab: "reports", label: "Reports", icon: ChartColumn, hint: "Sales, profit, sellers" },
          { tab: "expenses", label: "Expenses", icon: HandCoins, hint: "Rent, power, supplies: who was paid, how, for what", print: true },
          { tab: "salaries", label: "Salaries", icon: Banknote, hint: "Pay, advances, deductions and shortages per employee", print: true },
          { tab: "audit", label: "Audit log", icon: ScrollText, hint: "Who did what: removals, discounts, approvals, changes", print: true },
        ]], ["Setup", [
          { tab: "menu", label: "Menu & prices", icon: UtensilsCrossed, hint: "Items, sizes, prices, pictures, combos" },
          { tab: "choices", label: "Choices & happy hour", icon: SlidersHorizontal, hint: "Mixers, sides, offers by time" },
          { tab: "tables", label: "Tables & sections", icon: Armchair, hint: "Optional: tables grouped for the floor plan and reports" },
          { tab: "staff", label: "Staff & PINs", icon: Users, hint: "Who can log in, and as what" },
          { tab: "settings", label: "Settings", icon: Settings2, hint: "Business day, M-Pesa, receipts, emails" },
        ]]] as [string, NavItem[]][])
      : []),
  ];
  const current = groups.flatMap(([, items]) => items).find((i) => i.tab === tab)!;
  return (
    <main className="owner" style={{ zoom: TEXT_SIZES.find(([k]) => k === textSize)![2] }}>
      <nav className="owner-nav">
        <div className="owner-top">
          <button className="btn btn-quiet owner-back" onClick={onBack}>
            <ArrowLeft size={20} /> Orders
          </button>
          <button className="btn btn-primary owner-lock" onClick={onLock}>
            <LogOut size={20} /> LOCK
          </button>
        </div>
        {groups.map(([group, items]) => {
          const folds = group === "Setup";
          const open = !folds || setupOpen || items.some((i) => i.tab === tab);
          return (
          <div key={group} className="owner-group">
            {folds ? (
              <button className="owner-group-name owner-fold" onClick={() => setSetupOpen(!open)} aria-expanded={open}>
                {group} <ChevronDown size={16} className={open ? "open" : ""} />
              </button>
            ) : (
              <span className="owner-group-name">{group}</span>
            )}
            {open && items.map((item) => (
              <button key={item.tab} className={`owner-link ${tab === item.tab ? "on" : ""}`} onClick={() => setTab(item.tab)}>
                <item.icon size={20} />
                {item.label}
              </button>
            ))}
          </div>
          );
        })}
        <div className="owner-text-size no-print" role="group" aria-label="Text size">
          <span className="owner-group-name">Text size</span>
          <div className="segmented">
            {TEXT_SIZES.map(([key, letter], i) => (
              <button key={key} className={textSize === key ? "on" : ""} onClick={() => chooseSize(key)} aria-label={key === "xl" ? "Extra large" : key[0].toUpperCase() + key.slice(1)}>
                <span style={{ fontSize: 14 + i * 5 }}>{letter}</span>
              </button>
            ))}
          </div>
        </div>
        {canExit && (
          <button className="btn btn-quiet no-print" style={{ margin: "8px 12px" }} onClick={() => setExiting("ask")}>
            <MonitorUp size={20} /> Exit to desktop
          </button>
        )}
        <p className="owner-support no-print">
          <Phone size={16} /> Faida support
          <strong>{SUPPORT_PHONE}</strong>
          <span>call or WhatsApp</span>
        </p>
      </nav>
      <section className="owner-main">
        <header className="owner-title rise" key={tab}>
          <span className="owner-title-icon">
            <current.icon size={24} />
          </span>
          <div className="grow">
            <p className="print-only print-business">{business}</p>
            <h1>{current.label}</h1>
            <p className="muted no-print">{current.hint}</p>
            <p className="print-only">
              Printed {new Date().toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })} by {session.staff.name}
            </p>
          </div>
          {current.slip && <SlipButton kind={current.slip.kind} label={current.slip.label} />}
          {current.print && <PrintPageButton />}
        </header>
        <div className="owner-body">
          {tab === "dashboard" && <Dashboard onOpen={setTab} />}
          {tab === "shifts" && <ShiftsTab session={session} />}
          {tab === "credit" && <CreditTab session={session} />}
          {tab === "cash" && <CashTab session={session} />}
          {tab === "stock" && <StockTab session={session} />}
          {tab === "bills" && <FinishedBills session={session} embedded />}
          {tab === "printers" && <PrinterLog />}
          {tab === "closing" && <ClosingTab />}
          {tab === "reports" && <ReportsTab />}
          {tab === "expenses" && <ExpensesTab />}
          {tab === "salaries" && <SalariesTab />}
          {tab === "audit" && <AuditLog />}
          {tab === "menu" && <MenuEditor />}
          {tab === "choices" && <ChoicesEditor />}
          {tab === "tables" && <TablesEditor />}
          {tab === "staff" && <StaffEditor session={session} />}
          {tab === "settings" && <SettingsEditor />}
        </div>
      </section>
      {exiting && (
        <Modal title="Exit to the Windows desktop?" onClose={() => setExiting(null)}>
          {exiting === "ask" ? (
            <>
              <p style={{ margin: 0, fontSize: 18 }}>
                The full-screen counter closes. Faida keeps running in the background, so no orders are lost. To open it again, double-click the{" "}
                <strong>Faida POS</strong> icon on the desktop (it also opens by itself when the PC restarts).
              </p>
              <div className="row row-end">
                <button className="btn btn-quiet" onClick={() => setExiting(null)}>
                  Cancel
                </button>
                <button className="btn btn-primary" onClick={() => exitScreen().then(() => setExiting("closing"), () => setExiting(null))}>
                  EXIT TO DESKTOP
                </button>
              </div>
            </>
          ) : (
            <p style={{ margin: 0, fontSize: 18 }}>Closing… (a few seconds)</p>
          )}
        </Modal>
      )}
    </main>
  );
}

/** Everything that went to the printers today, newest first, with the exact printout. */
function PrinterLog() {
  const [rows, setRows] = useState<Printout[] | null>(null);
  const [open, setOpen] = useState<Printout | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => getPrintouts().then(setRows, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);
  if (!rows) return <div className="screen-loading">{error ?? <span className="spinner" />}</div>;
  const failed = rows.filter((r) => r.status === "not_printed").length;
  return (
    <>
      {failed > 0 && (
        <div className="alert-row">
          <TriangleAlert size={20} /> {failed} printouts did not come out. Open one to print it again.
        </div>
      )}
      <div className="list-table">
        {rows.map((r) => (
          <button key={r.id} className="list-row" onClick={() => setOpen(r)}>
            <span className="muted" style={{ minWidth: 60 }}>
              {time(r.created_at)}
            </span>
            <span className="pill">{r.printer === "kitchen" ? "Kitchen" : "Counter"}</span>
            <strong style={{ minWidth: 150 }}>
              {KIND_NAME[r.kind]} {r.kind === "receipt" || r.kind === "bill" ? `#${String(r.number).padStart(4, "0")}` : r.number}
            </strong>
            <span className="grow muted">{r.title}</span>
            {r.reprints > 0 && <span className="pill">×{r.reprints + 1}</span>}
            <StatusPill status={r.status} />
          </button>
        ))}
        {!rows.length && <p className="muted">Nothing printed yet.</p>}
      </div>
      {open && (
        <ReceiptDialog
          id={open.id}
          title={`${KIND_NAME[open.kind]} · ${open.title}`}
          free
          onReprint={() => (open.kind === "handover" ? reprintSlip(open.id) : reprint(open.id)).then(load)}
          onClose={() => (setOpen(null), load())}
        />
      )}
    </>
  );
}

const reprintSlip = (id: string) => api<Printout>(`/handover-slips/${id}/reprint`, { method: "POST" });

function AmountDialog({ title, children, onSubmit, onClose, submitLabel, extra, initial, zeroOk }: {
  title: string;
  children?: ReactNode;
  onSubmit: (amount: number) => Promise<unknown>;
  onClose: () => void;
  submitLabel: string;
  extra?: (amount: number) => boolean;
  initial?: number;
  zeroOk?: boolean;
}) {
  const [value, setValue] = useState(initial ? String(initial) : "");
  const [error, setError] = useState<string | null>(null);
  const n = Number(value || 0);
  const ok = (n > 0 || (!!zeroOk && value !== "")) && (extra ? extra(n) : true);
  const submit = () => ok && onSubmit(n).then(onClose, (e) => setError(errorText(e)));
  return (
    <Modal title={title} onClose={onClose} wide>
      <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
        <div className="choice-list grow">
          {children}
          <div className="field-box active">
            <span className="muted">Amount</span>
            <strong>{value ? formatKsh(n) : "—"}</strong>
          </div>
          <p className="error-text">{error ?? ""}</p>
          <button className="btn btn-primary" disabled={!ok} onClick={submit}>
            {submitLabel}
          </button>
        </div>
        <Keypad value={value} onChange={(v) => (setValue(v.replace(/^0+(?=\d)/, "")), setError(null))} onEnter={submit} maxLength={8} />
      </div>
    </Modal>
  );
}

function ShiftsTab({ session }: { session: Session }) {
  const isOwner = session.permissions.force_close_shift === "allow";
  const [rows, setRows] = useState<ShiftRow[] | null>(null);
  const [alerts, setAlerts] = useState<string[]>([]);
  const [staff, setStaff] = useState<{ id: string; name: string }[]>([]);
  const [floatFor, setFloatFor] = useState<{ id: string; name: string } | null>(null);
  const [pickFloat, setPickFloat] = useState(false);
  const [forcing, setForcing] = useState<ShiftRow | null>(null);
  const [shortage, setShortage] = useState<ShiftRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    getShifts().then(setRows, (e) => setError(errorText(e)));
    if (isOwner) getAlerts().then((a) => setAlerts(a.map((x) => x.message)), () => {});
  };
  useEffect(() => {
    load();
    getActiveStaff().then(setStaff, () => {});
  }, []);

  if (!rows) return <p className="muted">{error ?? "Loading…"}</p>;
  return (
    <>
      {alerts.map((a) => (
        <div key={a} className="alert-row">⚠ {a}</div>
      ))}
      <div className="row" style={{ marginBottom: 12 }}>
        <h2 className="section-title grow">Shifts today</h2>
        <button className="btn btn-primary" onClick={() => setPickFloat(true)}>
          GIVE FLOAT
        </button>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        <strong>Float</strong>: small change (e.g. KSh 1,000 in coins and notes) taken from the counter cash box and given to a waiter at the
        start of a shift, so they can give customers change. It is not a sale and not a gift: at hand-over the waiter brings it back with their
        cash sales, so the cash they must hand over = cash from their sales + float. Each shift below shows how much was expected and received.
      </p>
      <div className="list-table">
        {rows.map((r) => {
          const h = r.handover;
          return (
            <div key={r.shift.id} className="shift-row">
              <span className="grow">
                <strong>{r.shift.staff.name}</strong>
                <span className="muted">
                  {" "}
                  · {time(r.shift.started_at)}–{r.ended_at ? time(r.ended_at) : "now"}
                  {r.shift.float_amount ? ` · float ${formatKsh(r.shift.float_amount)}` : ""}
                </span>
              </span>
              {h ? (
                <>
                  <span>
                    {formatKsh(h.received)} of {formatKsh(h.expected)}
                  </span>
                  <span className={`result-badge ${h.difference === 0 ? "balanced" : h.difference < 0 ? "short" : "over"}`}>
                    {h.difference === 0 ? "Balanced" : h.difference < 0 ? `Short ${formatKsh(-h.difference)}` : `Over ${formatKsh(h.difference)}`}
                  </span>
                  <span className="muted">
                    {h.forced ? "Force-closed" : h.staff_agrees ? "Agreed" : "Disagreed"}
                    {h.staff_note ? `: "${h.staff_note}"` : ""}
                  </span>
                  {h.difference < 0 && isOwner && (
                    <button className="btn btn-quiet" onClick={() => setShortage(r)}>
                      {h.shortage_status ? h.shortage_status.replace("_", " ") : "Set status"}
                    </button>
                  )}
                </>
              ) : (
                <>
                  <span>Expected so far {formatKsh(r.expected)}</span>
                  <span className={r.open_bills ? "warn" : "muted"}>{r.open_bills} open orders</span>
                  {isOwner && r.shift.staff.id !== session.staff.id && (
                    <button className="btn btn-red" onClick={() => setForcing(r)}>
                      Force-close
                    </button>
                  )}
                </>
              )}
            </div>
          );
        })}
        {!rows.length && <p className="muted">No shifts yet today.</p>}
      </div>
      <p className="error-text">{error ?? ""}</p>

      {pickFloat && (
        <Modal title="Give a float to…" onClose={() => setPickFloat(false)}>
          <div className="choice-grid">
            {staff.map((s) => (
              <button key={s.id} className="choice" onClick={() => (setPickFloat(false), setFloatFor(s))}>
                {s.name}
              </button>
            ))}
          </div>
        </Modal>
      )}
      {floatFor && (
        <AmountDialog title={`Float for ${floatFor.name}`} submitLabel="GIVE FLOAT" onSubmit={(n) => giveFloat(floatFor.id, n).then(load)} onClose={() => setFloatFor(null)}>
          <p className="muted" style={{ margin: 0 }}>
            Change taken from the counter cash box for {floatFor.name} to give customers change. At hand-over they bring it back:
            it is added to the cash they must hand over.
          </p>
        </AmountDialog>
      )}
      {forcing && <ForceCloseDialog row={forcing} onDone={() => (setForcing(null), load())} onClose={() => setForcing(null)} />}
      {shortage?.handover && (
        <Modal title={`${shortage.shift.staff.name}: short ${formatKsh(-shortage.handover.difference)}`} onClose={() => setShortage(null)}>
          <p className="muted" style={{ margin: 0 }}>
            Faida never deducts pay by itself. Deducted: it comes off their pay account in Salaries (if their PIN is linked there). A deduction is
            your decision under your house rules and employment law.
          </p>
          <div className="choice-list">
            {(["paid_back", "deducted", "forgiven"] as const).map((o) => (
              <button key={o} className="choice" onClick={() => setShortageStatus(shortage.handover!.id, o).then(() => (setShortage(null), load()), (e) => setError(errorText(e)))}>
                {o === "paid_back" ? "Paid back" : o === "deducted" ? "Deducted" : "Forgiven"}
              </button>
            ))}
          </div>
        </Modal>
      )}
    </>
  );
}

function ForceCloseDialog({ row, onDone, onClose }: { row: ShiftRow; onDone: () => void; onClose: () => void }) {
  const [note, setNote] = useState("");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const received = Number(value || 0);
  const submit = () => note.trim() && forceClose(row.shift.id, received, note.trim()).then(onDone, (e) => setError(errorText(e)));
  return (
    <Modal title={`Force-close ${row.shift.staff.name}'s shift`} onClose={onClose} wide>
      <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
        <div className="choice-list grow">
          <p style={{ margin: 0, fontSize: 18 }}>
            {row.open_bills} open orders will be marked <strong>unpaid – waiter responsible</strong>. Record the cash you actually
            have from {row.shift.staff.name} (it may be 0); the rest becomes their shortage. Sign-off: not present.
          </p>
          <div className="field-box active">
            <span className="muted">Cash received</span>
            <strong>{formatKsh(received)}</strong>
          </div>
          <input className="text-input" placeholder="Why? (required)" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
          <p className="error-text">{error ?? ""}</p>
          <button className="btn btn-red" disabled={!note.trim()} onClick={submit}>
            FORCE-CLOSE
          </button>
        </div>
        <Keypad value={value} onChange={(v) => setValue(v.replace(/^0+/, ""))} onEnter={submit} maxLength={8} />
      </div>
    </Modal>
  );
}

function CreditTab({ session }: { session: Session }) {
  const isOwner = session.permissions.manage_business === "allow";
  const [customers, setCustomers] = useState<CreditCustomer[] | null>(null);
  const [collecting, setCollecting] = useState<CreditCustomer | null>(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<CreditCustomer | null>(null);
  const [viewing, setViewing] = useState<CreditCustomer | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => getCustomers().then((c) => setCustomers([...c].sort((a, b) => (a.oldest_unpaid ?? "9").localeCompare(b.oldest_unpaid ?? "9"))), (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);
  if (!customers) return <p className="muted">{error ?? "Loading…"}</p>;
  const total = customers.reduce((s, c) => s + c.owed, 0);
  const owing = customers.filter((c) => c.owed > 0);
  const paidUp = customers.filter((c) => c.owed === 0);
  const row = (c: CreditCustomer) => (
    <div key={c.id} className="shift-row">
      <span className="grow">
        <strong>{c.name}</strong>
        <span className="muted"> {c.phone ?? ""}</span>
      </span>
      {c.owed > 0 ? <span className="warn">owes {formatKsh(c.owed)}</span> : <span className="result-badge balanced">Paid up</span>}
      <span className="muted">limit {formatKsh(c.credit_limit)}</span>
      <span className="muted">{c.oldest_unpaid ? `since ${new Date(c.oldest_unpaid).toLocaleDateString("en-GB")}` : ""}</span>
      <button className="btn btn-quiet no-print" onClick={() => setViewing(c)}>
        History
      </button>
      {c.owed > 0 && (
        <button className="btn btn-primary no-print" onClick={() => setCollecting(c)}>
          Record payment
        </button>
      )}
      {isOwner && (
        <button className="btn btn-quiet no-print" onClick={() => setEditing(c)} aria-label={`Change ${c.name}`}>
          <Pencil size={18} /> {c.owed === 0 ? "Change / remove" : "Change"}
        </button>
      )}
    </div>
  );
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <h2 className="section-title grow">Debtors: {formatKsh(total)} owed, oldest first</h2>
        {isOwner && (
          <button className="btn btn-primary" onClick={() => setAdding(true)}>
            ADD CUSTOMER
          </button>
        )}
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        A customer can pay part of what they owe: the rest stays as their balance. When everything is paid they move to Paid up, where the owner can
        remove them from the list (their history is kept).
      </p>
      {message && <p className="ok-text">{message}</p>}
      <div className="list-table">
        {owing.map(row)}
        {!owing.length && <p className="muted">Nobody owes anything.</p>}
      </div>
      {paidUp.length > 0 && (
        <>
          <h2 className="section-title">Paid up</h2>
          <div className="list-table">{paidUp.map(row)}</div>
        </>
      )}
      <p className="error-text">{error ?? ""}</p>
      {collecting && (
        <CollectDialog
          customer={collecting}
          onDone={(after, paid) => (
            setCollecting(null),
            setMessage(`${after.name} paid ${formatKsh(paid)}. ${after.owed > 0 ? `Balance still owed: ${formatKsh(after.owed)}.` : "Paid in full."}`),
            load()
          )}
          onClose={() => setCollecting(null)}
        />
      )}
      {viewing && <CreditHistory customer={viewing} onClose={() => setViewing(null)} />}
      {adding && <AddCustomerDialog onDone={() => (setAdding(false), load())} onClose={() => setAdding(false)} />}
      {editing && <EditCustomerDialog customer={editing} onDone={() => (setEditing(null), load())} onClose={() => setEditing(null)} />}
    </>
  );
}

/** Every credit and payment of one customer, with the balance after each. */
function CreditHistory({ customer, onClose }: { customer: CreditCustomer; onClose: () => void }) {
  const [rows, setRows] = useState<CreditHistoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getCreditHistory(customer.id).then(setRows, (e) => setError(errorText(e)));
  }, [customer.id]);
  return (
    <Modal title={`${customer.name}: ${customer.owed > 0 ? `owes ${formatKsh(customer.owed)}` : "paid up"}`} onClose={onClose} wide>
      <div className="list-table movements">
        {rows?.map((r, i) => (
          <div key={i} className="row" style={{ fontSize: 17 }}>
            <span className="muted" style={{ minWidth: 130 }}>
              {new Date(r.at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
            </span>
            <span style={{ minWidth: 110 }}>{r.kind === "credit" ? "On credit" : "Paid"}</span>
            <span className="grow muted">
              {r.what}
              {r.by ? ` · ${r.by}` : ""}
            </span>
            <span className={r.kind === "credit" ? "warn" : "ok-text"} style={{ minWidth: 110, textAlign: "right" }}>
              {r.kind === "credit" ? "+" : "−"}
              {formatKsh(r.amount)}
            </span>
            <span style={{ minWidth: 150, textAlign: "right" }}>
              <span className="muted">balance </span>
              <strong>{formatKsh(r.balance)}</strong>
            </span>
          </div>
        ))}
        {rows?.length === 0 && <p className="muted">Nothing yet.</p>}
        {error && <p className="error-text">{error}</p>}
      </div>
    </Modal>
  );
}

function CollectDialog({ customer, onDone, onClose }: { customer: CreditCustomer; onDone: (after: CreditCustomer, paid: number) => void; onClose: () => void }) {
  const [method, setMethod] = useState<"cash" | "mpesa">("cash");
  const [code, setCode] = useState("");
  const [codeLength, setCodeLength] = useState(4);
  useEffect(() => {
    getSettings().then((s) => setCodeLength({ last4: 4, full: 10, none: 0 }[s.mpesa_code_entry]), () => {});
  }, []);
  return (
    <AmountDialog
      title={`${customer.name} pays (owes ${formatKsh(customer.owed)})`}
      submitLabel="RECORD PAYMENT"
      extra={(n) => n <= customer.owed && (method === "cash" || code.length === codeLength)}
      onSubmit={(n) => collectCredit(customer.id, { amount: n, method, mpesa_code: method === "mpesa" && codeLength ? code : undefined }).then((after) => onDone(after, n))}
      onClose={onClose}
    >
      <div className="row">
        <button className={`btn grow ${method === "cash" ? "btn-primary" : "btn-quiet"}`} onClick={() => setMethod("cash")}>
          CASH
        </button>
        <button className={`btn grow ${method === "mpesa" ? "btn-primary" : "btn-quiet"}`} onClick={() => setMethod("mpesa")}>
          M-PESA
        </button>
      </div>
      {method === "mpesa" && codeLength > 0 && <CodeKeypad value={code} length={codeLength} onChange={setCode} keyboard={false} />}
    </AmountDialog>
  );
}

function AddCustomerDialog({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  return (
    <AmountDialog
      title="New credit customer"
      submitLabel="ADD CUSTOMER"
      extra={() => !!name.trim()}
      onSubmit={(limit) => createCustomer({ name: name.trim(), phone: phone.trim() || null, credit_limit: limit }).then(onDone)}
      onClose={onClose}
    >
      <input className="text-input" placeholder="Name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
      <input className="text-input" placeholder="Phone" value={phone} maxLength={20} onChange={(e) => setPhone(e.target.value)} />
      <p className="muted" style={{ margin: 0 }}>
        Credit limit (amount):
      </p>
    </AmountDialog>
  );
}

/** Owner only: name, phone and credit limit. A limit of 0 stops new credit; a customer
 * who owes nothing can be removed from the list (kept in the records). */
function EditCustomerDialog({ customer, onDone, onClose }: { customer: CreditCustomer; onDone: () => void; onClose: () => void }) {
  const [name, setName] = useState(customer.name);
  const [phone, setPhone] = useState(customer.phone ?? "");
  const [error, setError] = useState<string | null>(null);
  const remove = () => updateCustomer(customer.id, { active: false }).then(onDone, (e) => setError(errorText(e)));
  return (
    <AmountDialog
      title={`Change ${customer.name}`}
      submitLabel="SAVE"
      initial={customer.credit_limit}
      zeroOk
      extra={() => !!name.trim()}
      onSubmit={(limit) => updateCustomer(customer.id, { name: name.trim(), phone: phone.trim(), credit_limit: limit }).then(onDone)}
      onClose={onClose}
    >
      <input className="text-input" placeholder="Name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
      <input className="text-input" placeholder="Phone" value={phone} maxLength={20} onChange={(e) => setPhone(e.target.value)} />
      {customer.owed === 0 && (
        <button className="btn btn-quiet" onClick={remove}>
          REMOVE FROM LIST
        </button>
      )}
      <p className="error-text">{error ?? ""}</p>
      <p className="muted" style={{ margin: 0 }}>
        Credit limit (owes {formatKsh(customer.owed)} now; 0 stops new credit):
      </p>
    </AmountDialog>
  );
}

const PAID = { cash: "Cash", mpesa: "M-Pesa", card: "Card", credit: "Credit (owed)" } as const;

/** Today's money by how it was paid. Only cash goes in the box; M-Pesa is on the till. */
function Takings({ t }: { t: NonNullable<CashBox["takings"]> }) {
  const tile = (label: string, value: number, note: string) => (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <strong className="kpi-value">{formatKsh(value)}</strong>
      <span className="kpi-note">{note}</span>
    </div>
  );
  return (
    <>
      <h2 className="section-title">Today's sales by payment</h2>
      <div className="kpis" style={{ marginBottom: 16 }}>
        <div className="kpi kpi-big">
          <span className="kpi-label">Total sales</span>
          <strong className="kpi-value">{formatKsh(t.total)}</strong>
          <span className="kpi-note">{t.unpaid > 0 ? `of which ${formatKsh(t.unpaid)} unpaid (waiter responsible)` : "every finished order today"}</span>
        </div>
        {tile("Cash", t.cash, t.credit_paid_cash ? `+ ${formatKsh(t.credit_paid_cash)} credit paid in cash` : "in waiters' hands until hand-over")}
        {tile("M-Pesa", t.mpesa, t.credit_paid_mpesa ? `+ ${formatKsh(t.credit_paid_mpesa)} credit paid by M-Pesa` : `on the till${t.card ? ` · card ${formatKsh(t.card)}` : ""}`)}
        {tile("Credit", t.credit, "sold on credit today, still owed")}
      </div>
    </>
  );
}

function CashTab({ session }: { session: Session }) {
  const isOwner = session.permissions.manage_business === "allow";
  const [box, setBox] = useState<CashBox | null>(null);
  const [dialog, setDialog] = useState<null | "payout" | "in" | "out">(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getCashBox().then(setBox, (e) => setError(errorText(e)));
  }, []);
  if (!box) return <p className="muted">{error ?? "Loading…"}</p>;
  const titles = { payout: "Pay-out from takings", in: "Add cash to the box", out: "Take cash out of the box" };
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <div className="grow">
          <div className="muted" style={{ fontSize: 18 }}>
            Cash that should be in the counter box
          </div>
          <div style={{ fontSize: 44, fontWeight: 800 }}>{formatKsh(box.expected)}</div>
        </div>
        <button className="btn btn-primary" onClick={() => (setNote(""), setDialog("payout"))}>
          PAY-OUT
        </button>
        {isOwner && (
          <>
            <button className="btn btn-quiet" onClick={() => (setNote(""), setDialog("in"))}>
              Add cash
            </button>
            <button className="btn btn-quiet" onClick={() => (setNote(""), setDialog("out"))}>
              Take cash out
            </button>
          </>
        )}
      </div>
      {box.takings && <Takings t={box.takings} />}
      <h2 className="section-title">Payments today</h2>
      <div className="list-table">
        {box.payments.map((p, i) => (
          <div key={i} className="shift-row">
            <span className="muted">{time(p.at)}</span>
            <span className={`status-tag pay-${p.method === "credit_paid" ? p.paid_by : p.method}`} style={{ minWidth: 150, textAlign: "center" }}>
              {p.method === "credit_paid" ? `Credit paid · ${PAID[p.paid_by ?? "cash"]}` : PAID[p.method]}
            </span>
            <span className="grow">
              {p.what} <span className="muted">· {p.by}</span>
              {p.ref && <span className="muted"> · code {p.ref}</span>}
            </span>
            <strong>{formatKsh(p.amount)}</strong>
          </div>
        ))}
        {!box.payments.length && <p className="muted">No payments yet today.</p>}
      </div>
      <h2 className="section-title">Cash in and out of the box today</h2>
      <div className="list-table">
        {box.today.map((m) => (
          <div key={m.id} className="shift-row">
            <span className="muted">{time(m.at)}</span>
            <span>{KIND[m.kind]}</span>
            <span className="grow muted">
              {m.note} · {m.by}
            </span>
            <span className={m.amount < 0 ? "warn" : ""}>{m.amount < 0 ? `−${formatKsh(-m.amount)}` : `+${formatKsh(m.amount)}`}</span>
          </div>
        ))}
        {!box.today.length && <p className="muted">Nothing yet today.</p>}
      </div>
      {dialog && (
        <AmountDialog
          title={titles[dialog]}
          submitLabel="RECORD"
          extra={() => !!note.trim()}
          onSubmit={(n) =>
            (dialog === "payout" ? recordPayout(n, note.trim()) : ownerCash(dialog === "in" ? n : -n, note.trim())).then(setBox)
          }
          onClose={() => setDialog(null)}
        >
          <input
            className="text-input"
            placeholder={dialog === "payout" ? "What for? e.g. Ice" : "Note, e.g. Change for tonight"}
            value={note}
            maxLength={200}
            onChange={(e) => setNote(e.target.value)}
          />
        </AmountDialog>
      )}
    </>
  );
}
