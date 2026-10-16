import { FileSpreadsheet, Printer } from "lucide-react";
import { useEffect, useState } from "react";
import {
  addExpense,
  download,
  ApiError,
  closeDay,
  getClosing,
  getExpenses,
  getReport,
  reverseExpense,
  type Closing,
  type Expense,
  type Report,
} from "../services/api";
import { Keypad } from "../shared/Keypad";
import { toast } from "../shared/Toast";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";
import { COMP_LABEL } from "./billLines";
import { BarList, ClosingView, ProfitBlock, Row, SalesBlock, Section } from "../shared/ReportParts";

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const shift = (day: string, days: number) => {
  const d = new Date(`${day}T12:00:00`);
  d.setDate(d.getDate() + days);
  return iso(d);
};
/** Excel for the accountant, and Print / Save as PDF (the browser's print dialog, with
 * the owner screens' chrome hidden by the print stylesheet). */
function ExportButtons({ onExcel }: { onExcel: () => Promise<unknown> }) {
  return (
    <>
      <button className="btn btn-quiet no-print" onClick={() => onExcel().catch((e) => toast(errorText(e), "error"))}>
        <FileSpreadsheet size={18} /> Excel
      </button>
      <button className="btn btn-quiet no-print" onClick={() => window.print()}>
        <Printer size={18} /> Print / PDF
      </button>
    </>
  );
}

const nice = (day: string) => new Date(`${day}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

/** The business day's closing (masterplan 4.9). Supervisors see it without profit. */
export function ClosingTab() {
  const [closing, setClosing] = useState<Closing | null>(null);
  const [today, setToday] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [counted, setCounted] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = (day?: string) =>
    getClosing(day).then((c) => {
      setClosing(c);
      if (!day) setToday(c.day);
    }, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);

  if (!closing) return <p className="muted">{error ?? "Loading…"}</p>;
  const blockers = closing.report.blockers;
  const blocked = blockers.open_shifts.length > 0 || blockers.open_bills.length > 0;

  const close = () =>
    closeDay(closing.day, counted ? Number(counted) : undefined).then((c) => (setClosing(c), setConfirming(false)), (e) => (setConfirming(false), setError(errorText(e))));

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className="btn btn-quiet" onClick={() => load(shift(closing.day, -1))}>
          ‹
        </button>
        <h2 className="section-title" style={{ margin: 0 }}>
          Business day {nice(closing.day)}
        </h2>
        <button className="btn btn-quiet" disabled={closing.day === today} onClick={() => load(shift(closing.day, 1))}>
          ›
        </button>
        <span className="grow" />
        <ExportButtons onExcel={() => download(`/closing/export?day=${closing.day}`, `closing-${closing.day}.xlsx`)} />
        {closing.closed ? (
          <span className="status-tag paid">
            Closed by {closing.closed_by} at {new Date(closing.closed_at!).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
            {closing.cash_box_counted !== null && ` · box counted ${formatKsh(closing.cash_box_counted)}`}
          </span>
        ) : (
          <button className="btn btn-primary" disabled={blocked} onClick={() => setConfirming(true)}>
            CLOSE DAY
          </button>
        )}
      </div>
      {!closing.closed && blocked && (
        <div className="alert-row">
          Not ready to close:
          {blockers.open_shifts.length > 0 && ` shifts still open (${blockers.open_shifts.join(", ")})`}
          {blockers.open_bills.length > 0 && ` · ${blockers.open_bills.length} open bills (${blockers.open_bills.map((b) => b.place).join(", ")})`}
        </div>
      )}
      <p className="error-text">{error ?? ""}</p>
      <ClosingView report={closing.report} />
      {confirming && (
        <Modal title={`Close ${nice(closing.day)}?`} onClose={() => setConfirming(false)} wide>
          <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
            <div className="choice-list grow">
              <p style={{ margin: 0, fontSize: 18 }}>
                Count the counter cash box (optional). It should hold <strong>{formatKsh(closing.report.cash_box.expected_now)}</strong>.
              </p>
              <div className="field-box active">
                <span className="muted">Counted in the box</span>
                <strong>{counted ? formatKsh(Number(counted)) : "—"}</strong>
              </div>
              {counted && Number(counted) !== closing.report.cash_box.expected_now && (
                <p className="warn" style={{ margin: 0, fontSize: 18 }}>
                  Difference: {formatKsh(Number(counted) - closing.report.cash_box.expected_now)}
                </p>
              )}
              <p className="muted" style={{ margin: 0 }}>
                The report is saved as it is now and can't be changed afterwards.
              </p>
              <button className="btn btn-primary" onClick={close}>
                CLOSE THE DAY
              </button>
            </div>
            <Keypad value={counted} onChange={(v) => setCounted(v.replace(/^0+/, ""))} onEnter={close} maxLength={8} allowEmptyEnter />
          </div>
        </Modal>
      )}
    </>
  );
}

type Preset = "today" | "yesterday" | "week" | "month" | "last_month";

function range(preset: Preset, today: string): [string, string] {
  const t = new Date(`${today}T12:00:00`);
  switch (preset) {
    case "yesterday":
      return [shift(today, -1), shift(today, -1)];
    case "week": {
      const monday = shift(today, -((t.getDay() + 6) % 7));
      return [monday, today];
    }
    case "month":
      return [iso(new Date(t.getFullYear(), t.getMonth(), 1)), today];
    case "last_month":
      return [iso(new Date(t.getFullYear(), t.getMonth() - 1, 1)), iso(new Date(t.getFullYear(), t.getMonth(), 0))];
    default:
      return [today, today];
  }
}

/** Owner reports for any period (masterplan 4.9). */
export function ReportsTab() {
  const [today, setToday] = useState<string | null>(null);
  const [period, setPeriod] = useState<[string, string] | null>(null);
  const [preset, setPreset] = useState<Preset | null>("today");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Only the first answer sets the period, so it never undoes a choice made meanwhile.
    getClosing().then((c) => (setToday(c.day), setPeriod((p) => p ?? [c.day, c.day])), (e) => setError(errorText(e)));
  }, []);
  useEffect(() => {
    if (period) getReport(...period).then(setReport, (e) => setError(errorText(e)));
  }, [period]);

  if (!today || !period) return <p className="muted">{error ?? "Loading…"}</p>;
  const presets: [Preset, string][] = [["today", "Today"], ["yesterday", "Yesterday"], ["week", "This week"], ["month", "This month"], ["last_month", "Last month"]];
  const b = report?.breakdown;
  return (
    <>
      <div className="row" style={{ flexWrap: "wrap", marginBottom: 12 }}>
        {presets.map(([p, label]) => (
          <button key={p} className={`cat ${preset === p ? "selected" : ""}`} onClick={() => (setPreset(p), setPeriod(range(p, today)))}>
            {label}
          </button>
        ))}
        <input className="text-input" type="date" value={period[0]} max={period[1]} onChange={(e) => (setPreset(null), setPeriod([e.target.value, period[1]]))} />
        <span className="muted">to</span>
        <input className="text-input" type="date" value={period[1]} min={period[0]} max={today} onChange={(e) => (setPreset(null), setPeriod([period[0], e.target.value]))} />
        <span className="grow" />
        <ExportButtons onExcel={() => download(`/reports/export?start=${period[0]}&end=${period[1]}`, `report-${period[0]}-to-${period[1]}.xlsx`)} />
      </div>
      <p className="error-text">{error ?? ""}</p>
      {!report || !b ? (
        <p className="muted">Loading…</p>
      ) : (
        <div className="report-grid">
          <Section title="Profit">
            <ProfitBlock profit={report.profit} />
          </Section>
          <Section title="Sales">
            <SalesBlock sales={report.sales} />
            {report.credit_collected.total > 0 && <Row label="Credit collected" value={formatKsh(report.credit_collected.total)} />}
          </Section>
          <Section title="Sales by hour">
            <BarList rows={b.by_hour.map((h) => ({ label: `${String(h.hour).padStart(2, "0")}:00`, value: h.sales }))} />
          </Section>
          <Section title="Sales by category">
            <BarList rows={b.by_category.map((c) => ({ label: c.category, value: c.sales }))} />
          </Section>
          {b.by_section.length > 1 && (
            <Section title="Sales by section">
              <BarList rows={b.by_section.map((r) => ({ label: r.section, value: r.sales }))} />
            </Section>
          )}
          <Section title="Bar and kitchen">
            <BarList rows={b.by_station.map((r) => ({ label: r.station === "bar" ? "Bar" : "Kitchen", value: r.sales }))} />
          </Section>
          <Section title="Sales by waiter">
            <BarList rows={b.by_waiter.map((w) => ({ label: w.waiter, value: w.sales, note: `${w.bills} bills` }))} />
          </Section>
          <Section title="Best sellers">
            <BarList rows={b.best.map((i) => ({ label: i.item, value: i.sales, note: `× ${i.quantity}` }))} />
          </Section>
          {report.comps.items.length > 0 && (
            <Section title={`Given free: ${formatKsh(report.comps.total)} at menu price`}>
              {Object.entries(
                report.comps.items.reduce<Record<string, number>>((acc, c) => ((acc[c.reason] = (acc[c.reason] ?? 0) + c.value), acc), {}),
              ).map(([reason, value]) => (
                <Row key={reason} label={COMP_LABEL[reason] ?? reason} value={formatKsh(value)} />
              ))}
            </Section>
          )}
          <Section title="Worst sellers">
            {b.worst.map((i) => (
              <Row key={i.item} label={i.item} value={i.quantity ? `${formatKsh(i.sales)} × ${i.quantity}` : "not sold"} />
            ))}
          </Section>
          <Section title="All items">
            {b.by_item.map((i) => (
              <Row key={i.item} label={`${i.item} × ${i.quantity}`} value={formatKsh(i.sales)} />
            ))}
            {!b.by_item.length && <p className="rp-empty">No sales.</p>}
          </Section>
          <Section title="Shortages by waiter">
            {report.shortages.map((s) => (
              <Row key={s.staff} label={`${s.staff}: ${s.times_short} of ${s.shifts} shifts short${s.times_over ? `, ${s.times_over} over` : ""}`} value={formatKsh(s.short)} tone={s.short ? "bad" : undefined} />
            ))}
            {!report.shortages.length && <p className="rp-empty">No hand-overs.</p>}
          </Section>
          <Section title="Stock variance">
            {report.variance.map((v, i) => (
              <Row key={i} label={`${nice(v.day)} · ${v.item}: ${v.variance}`} value={formatKsh(v.value ?? 0)} tone={(v.value ?? 0) < 0 ? "warn" : undefined} />
            ))}
            {!report.variance.length && <p className="rp-empty">No differences found.</p>}
            <Row label="Stock value now (buying price)" value={formatKsh(report.stock.value ?? 0)} strong />
          </Section>
          <Section title="Debtors">
            {report.debtors.map((d) => (
              <Row key={d.name} label={`${d.name}${d.since ? ` · since ${nice(d.since.slice(0, 10))}` : ""}`} value={formatKsh(d.owed)} />
            ))}
            {!report.debtors.length && <p className="rp-empty">Nobody owes.</p>}
          </Section>
        </div>
      )}
    </>
  );
}

const CATEGORIES = ["rent", "power", "water", "salaries", "transport", "repairs", "licences", "supplies", "other"];

/** Running costs (owner). Pay-outs from takings are counted as expenses automatically. */
export function ExpensesTab() {
  const [today, setToday] = useState<string | null>(null);
  const [rows, setRows] = useState<Expense[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = (day: string) => getExpenses(iso(new Date(new Date(`${day}T12:00:00`).getFullYear(), new Date(`${day}T12:00:00`).getMonth(), 1)), day).then(setRows, (e) => setError(errorText(e)));
  useEffect(() => {
    getClosing().then((c) => (setToday(c.day), load(c.day)), (e) => setError(errorText(e)));
  }, []);
  if (!today || !rows) return <p className="muted">{error ?? "Loading…"}</p>;
  const total = rows.reduce((s, r) => s + r.amount, 0);
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <h2 className="section-title grow" style={{ margin: 0 }}>
          Expenses this month: {formatKsh(total)}
        </h2>
        <button className="btn btn-primary" onClick={() => setAdding(true)}>
          ADD EXPENSE
        </button>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        Pay-outs taken from the day's cash are counted as expenses in profit automatically.
      </p>
      <div className="list-table">
        {rows.map((e) => (
          <div key={e.id} className={`shift-row ${e.reversed || e.is_reversal ? "reversed-row" : ""}`}>
            <span className="muted" style={{ minWidth: 110 }}>
              {nice(e.business_day)}
            </span>
            <strong style={{ minWidth: 110 }}>{e.category}</strong>
            <span className="grow muted">
              {e.note} {e.from_cash_box ? "· from cash box" : ""} · {e.by}
            </span>
            <span>{formatKsh(e.amount)}</span>
            {!e.reversed && !e.is_reversal && (
              <button className="btn btn-quiet" onClick={() => reverseExpense(e.id).then(() => load(today), (err) => setError(errorText(err)))}>
                Reverse
              </button>
            )}
          </div>
        ))}
        {!rows.length && <p className="muted">No expenses this month.</p>}
      </div>
      <p className="error-text">{error ?? ""}</p>
      {adding && <AddExpense onDone={() => (setAdding(false), load(today))} onClose={() => setAdding(false)} />}
    </>
  );
}

function AddExpense({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const [category, setCategory] = useState("rent");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [fromBox, setFromBox] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = () =>
    value && addExpense({ category, amount: Number(value), note: note.trim() || undefined, from_cash_box: fromBox }).then(onDone, (e) => setError(errorText(e)));
  return (
    <Modal title="Add expense" onClose={onClose} wide>
      <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
        <div className="choice-list grow">
          <div className="choice-grid">
            {CATEGORIES.map((c) => (
              <button key={c} className={`choice ${category === c ? "selected" : ""}`} onClick={() => setCategory(c)}>
                {c.charAt(0).toUpperCase() + c.slice(1)}
              </button>
            ))}
          </div>
          <div className="field-box active">
            <span className="muted">Amount</span>
            <strong>{value ? formatKsh(Number(value)) : "—"}</strong>
          </div>
          <input className="text-input" placeholder="Note, e.g. KPLC tokens" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
          <label className="row" style={{ fontSize: 18 }}>
            <input type="checkbox" checked={fromBox} onChange={(e) => setFromBox(e.target.checked)} style={{ width: 28, height: 28 }} />
            Paid in cash from the counter box
          </label>
          <p className="error-text">{error ?? ""}</p>
          <button className="btn btn-primary" disabled={!value} onClick={save}>
            SAVE
          </button>
        </div>
        <Keypad value={value} onChange={(v) => setValue(v.replace(/^0+/, ""))} onEnter={save} maxLength={8} />
      </div>
    </Modal>
  );
}
