import type { ReactNode } from "react";
import type { ClosingReport, Profit, SalesSummary } from "../services/api";
import { formatKsh } from "./money";
import "./report.css";

export function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="rp-section">
      <header className="rp-head">
        <h3>{title}</h3>
        {aside}
      </header>
      {children}
    </section>
  );
}

export function Row({ label, value, strong, tone }: { label: ReactNode; value: ReactNode; strong?: boolean; tone?: "warn" | "bad" | "good" }) {
  return (
    <div className={`rp-row ${strong ? "strong" : ""} ${tone ?? ""}`}>
      <span>{label}</span>
      <span className="rp-num">{value}</span>
    </div>
  );
}

/** One series of magnitudes as horizontal bars: one hue, values printed beside each
 * bar (the list doubles as its own table), hover shows the exact figure. */
export function BarList({ rows, unit = "KSh" }: { rows: { label: string; value: number; note?: string }[]; unit?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (!rows.length) return <p className="rp-empty">Nothing in this period.</p>;
  return (
    <div className="rp-bars" role="table">
      {rows.map((r) => (
        <div key={r.label} className="rp-bar-row" role="row" title={`${r.label}: ${unit} ${formatKsh(r.value)}${r.note ? ` (${r.note})` : ""}`}>
          <span className="rp-bar-label" role="cell">
            {r.label}
          </span>
          <span className="rp-bar-track" role="presentation">
            <span className="rp-bar" style={{ width: `${(r.value / max) * 100}%` }} />
          </span>
          <span className="rp-num" role="cell">
            {formatKsh(r.value)}
            {r.note && <small> {r.note}</small>}
          </span>
        </div>
      ))}
    </div>
  );
}

export function Big({ label, value, tone }: { label: string; value: string; tone?: "warn" | "bad" | "good" }) {
  return (
    <div className={`rp-big ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function SalesBlock({ sales }: { sales: SalesSummary }) {
  return (
    <>
      <div className="rp-bigs">
        <Big label="Sales" value={formatKsh(sales.total)} />
        <Big label="Cash" value={formatKsh(sales.cash)} />
        <Big label="M-Pesa" value={formatKsh(sales.mpesa)} />
        <Big label="Credit" value={formatKsh(sales.credit)} />
      </div>
      <Row label={`Bills (average ${formatKsh(sales.average_bill)})`} value={sales.bills} />
      {sales.unpaid > 0 && <Row label="Unpaid – waiter responsible" value={formatKsh(sales.unpaid)} tone="warn" />}
      {sales.discounts > 0 && <Row label="Discounts given" value={formatKsh(sales.discounts)} />}
      {sales.tips > 0 && <Row label="M-Pesa tips (not sales)" value={formatKsh(sales.tips)} />}
    </>
  );
}

const CATEGORY: Record<string, string> = { payouts: "Pay-outs from takings" };
const label = (k: string) => CATEGORY[k] ?? k.charAt(0).toUpperCase() + k.slice(1);

export function ProfitBlock({ profit }: { profit: Profit }) {
  return (
    <>
      <Row label="Sales" value={formatKsh(profit.sales)} />
      <Row label="− Cost of goods sold" value={formatKsh(profit.cost_of_sales)} />
      <Row label="= Gross profit" value={formatKsh(profit.gross_profit)} strong />
      <Row label="− Waste" value={formatKsh(profit.waste)} />
      <Row label={profit.variance < 0 ? "− Stock missing (stock takes)" : "+ Stock found (stock takes)"} value={formatKsh(Math.abs(profit.variance))} tone={profit.variance < 0 ? "warn" : undefined} />
      {Object.entries(profit.expenses_by_category).map(([k, v]) => (
        <Row key={k} label={`− ${label(k)}`} value={formatKsh(v)} />
      ))}
      <Row label="= REAL PROFIT" value={`${profit.real_profit < 0 ? "−" : ""}${formatKsh(Math.abs(profit.real_profit))}`} strong tone={profit.real_profit < 0 ? "bad" : "good"} />
    </>
  );
}

const diff = (d: number) => (d === 0 ? "Balanced" : d < 0 ? `Short ${formatKsh(-d)}` : `Over ${formatKsh(d)}`);

/** The daily closing (masterplan 4.9), as the counter and the phone both show it. */
export function ClosingView({ report }: { report: ClosingReport }) {
  const box = report.cash_box;
  return (
    <div className="rp">
      <Section title="Sales">
        <SalesBlock sales={report.sales} />
        {report.credit_collected.total > 0 && (
          <Row label={`Credit collected (cash ${formatKsh(report.credit_collected.cash)}, M-Pesa ${formatKsh(report.credit_collected.mpesa)})`} value={formatKsh(report.credit_collected.total)} />
        )}
      </Section>

      <Section title="Waiters' hand-overs">
        {report.waiters.map((w, i) => (
          <Row
            key={i}
            label={`${w.staff} · received by ${w.receiver}${w.forced ? " · force-closed" : w.agrees === false ? " · disagreed" : ""}`}
            value={`${formatKsh(w.received)} of ${formatKsh(w.expected)} · ${diff(w.difference)}`}
            tone={w.difference < 0 ? "bad" : w.difference > 0 ? "warn" : undefined}
          />
        ))}
        {!report.waiters.length && <p className="rp-empty">No hand-overs yet.</p>}
      </Section>

      <Section title="Counter cash box">
        <Row label="Cash handed over" value={formatKsh(box.today.handover ?? 0)} />
        <Row label="Credit paid in cash" value={formatKsh(box.today.credit_collected ?? 0)} />
        <Row label="Floats given" value={formatKsh(-(box.today.float ?? 0))} />
        {box.payouts.map((p, i) => (
          <Row key={i} label={`Pay-out: ${p.note ?? ""} (${p.by})`} value={formatKsh(p.amount)} />
        ))}
        {(box.today.owner ?? 0) !== 0 && <Row label="Owner in/out" value={formatKsh(box.today.owner)} />}
        <Row label="Should be in the box now" value={formatKsh(box.expected_now)} strong />
      </Section>

      {(report.voids.length > 0 || report.discounts.length > 0 || report.cancelled.length > 0) && (
        <Section title="Voids, discounts and cancelled bills">
          {report.voids.map((v, i) => (
            <Row key={`v${i}`} label={`#${String(v.bill).padStart(4, "0")} ${v.item} (${v.reason === "not_prepared" ? "not prepared" : "already prepared"}) · ${v.asked_by} → ${v.approved_by}`} value={formatKsh(v.price)} />
          ))}
          {report.discounts.map((d, i) => (
            <Row key={`d${i}`} label={`#${String(d.bill).padStart(4, "0")} discount${d.reason ? `: ${d.reason}` : ""} · ${d.asked_by} → ${d.approved_by}`} value={formatKsh(d.amount)} />
          ))}
          {report.cancelled.map((c, i) => (
            <Row key={`c${i}`} label={`#${String(c.bill).padStart(4, "0")} cancelled after payment · ${c.asked_by} → ${c.approved_by}`} value={formatKsh(c.total ?? 0)} tone="warn" />
          ))}
        </Section>
      )}

      {report.unpaid_bills.length > 0 && (
        <Section title="Unpaid bills (waiter responsible)">
          {report.unpaid_bills.map((u) => (
            <Row key={u.bill} label={`#${String(u.bill).padStart(4, "0")} ${u.place} · ${u.waiter}`} value={formatKsh(u.amount)} tone="warn" />
          ))}
        </Section>
      )}

      <Section title="Stock">
        {report.stock_variance.map((v, i) => (
          <Row key={i} label={`${v.item}: ${v.variance}`} value={v.value === null ? "" : formatKsh(v.value)} tone={v.variance.startsWith("Missing") ? "warn" : undefined} />
        ))}
        {report.stock.check.map((s) => (
          <Row key={s.item} label={`${s.item}: below zero, count it`} value={s.level} tone="bad" />
        ))}
        {report.stock.low.map((s) => (
          <Row key={s.item} label={`${s.item}: low`} value={s.level} tone="warn" />
        ))}
        {!report.stock_variance.length && !report.stock.low.length && !report.stock.check.length && <p className="rp-empty">Nothing to flag.</p>}
      </Section>

      {report.profit && (
        <Section title="Profit (owner only)">
          <ProfitBlock profit={report.profit} />
        </Section>
      )}
    </div>
  );
}
