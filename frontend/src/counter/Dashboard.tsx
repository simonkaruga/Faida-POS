import {
  ArrowDownRight,
  ArrowUpRight,
  Armchair,
  CheckCircle2,
  Clock3,
  OctagonAlert,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, getDashboard, type Dashboard as Data } from "../services/api";
import { initials, since } from "../shared/look";
import { formatKsh } from "../shared/money";
import { BarList } from "../shared/ReportParts";
import "./dashboard.css";

export const weekday = (day: string) => new Date(`${day}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short" });
const time = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const METHOD: Record<string, string> = { cash: "Cash", mpesa: "M-Pesa", card: "Card", credit: "Credit", unpaid: "Unpaid" };

/** The owner area's home page, like the home screens of Square, Toast and Lightspeed:
 * today so far against the same weekday last week, what's selling, who's on, and what
 * needs a look. Refreshes itself every 30 seconds. */
export function Dashboard({ onOpen }: { onOpen: (tab: "shifts" | "stock" | "bills" | "reports") => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [at, setAt] = useState<Date | null>(null);
  const load = () =>
    getDashboard().then(
      (d) => (setData(d), setAt(new Date()), setError(null)),
      (e) => setError(e instanceof ApiError ? e.message : "Couldn't load the dashboard."),
    );
  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  if (!data) return <div className="screen-loading">{error ?? <span className="spinner" />}</div>;
  const lastDay = `last ${weekday(data.compare_day)}`;
  const { today, last_week_so_far: before } = data;

  return (
    <div className="dash">
      <div className="dash-head">
        <span className="live-dot" aria-hidden />
        <span>
          <strong>{new Date(`${data.day}T12:00:00`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}</strong>
          <span className="muted"> · business day so far, compared with {lastDay} at this time</span>
        </span>
        <span className="grow" />
        {error && <span className="warn">{error}</span>}
        <button className="btn btn-quiet" onClick={load}>
          <RefreshCw size={18} /> {at ? `Updated ${time(at.toISOString())}` : "Refresh"}
        </button>
      </div>

      <div className="kpis">
        <Kpi label="Sales" value={formatKsh(today.sales)} now={today.sales} then={before.sales} lastDay={lastDay} big />
        <Kpi label="Orders paid" value={String(today.bills)} now={today.bills} then={before.bills} lastDay={lastDay} />
        <Kpi label="Average bill" value={formatKsh(today.average_bill)} now={today.average_bill} then={before.average_bill} lastDay={lastDay} />
        {data.gross_profit ? (
          <div className="kpi">
            <span className="kpi-label">Gross profit</span>
            <strong className="kpi-value">{formatKsh(data.gross_profit.amount)}</strong>
            <span className="kpi-note">{data.gross_profit.margin === null ? "No sales yet" : `${data.gross_profit.margin}% of sales, at buying price`}</span>
          </div>
        ) : (
          <div className="kpi">
            <span className="kpi-label">Items sold</span>
            <strong className="kpi-value">{today.items}</strong>
            <span className="kpi-note">Excludes free and removed items</span>
          </div>
        )}
      </div>

      <div className="dash-row two">
        <section className="card">
          <header className="card-head">
            <h3>Sales by hour</h3>
            <span className="legend">
              <i className="sw today" /> Today <i className="sw before" /> {lastDay[0].toUpperCase() + lastDay.slice(1)}
            </span>
          </header>
          <HourChart data={data} />
          <p className="card-foot muted">
            {data.last_week_total
              ? `${lastDay[0].toUpperCase() + lastDay.slice(1)} took ${formatKsh(data.last_week_total)} for the whole day.`
              : `No sales recorded ${lastDay}: the comparison starts after a week of selling.`}
          </p>
        </section>
        <section className="card">
          <header className="card-head">
            <h3>Right now</h3>
          </header>
          <div className="now-tables">
            <Armchair size={26} />
            <div className="grow">
              <strong>
                {data.live.tables_in_use} of {data.live.tables}
              </strong>{" "}
              tables in use
              <div className="meter">
                <span style={{ width: `${data.live.tables ? (data.live.tables_in_use / data.live.tables) * 100 : 0}%` }} />
              </div>
            </div>
          </div>
          <div className="now-grid">
            <div>
              <span className="muted">Open orders</span>
              <strong>{data.live.open_bills}</strong>
            </div>
            <div>
              <span className="muted">Still to collect</span>
              <strong>{formatKsh(data.live.open_value)}</strong>
            </div>
          </div>
          {data.live.oldest_open && (
            <p className={`now-oldest ${Date.now() - new Date(data.live.oldest_open).getTime() > 3 * 3600_000 ? "warn" : "muted"}`}>
              <Clock3 size={16} /> Oldest open order: {since(data.live.oldest_open)}
            </p>
          )}
          <h4 className="mini-title">On shift</h4>
          <div className="on-shift">
            {data.live.on_shift.map((s) => (
              <span key={s.staff} className="shift-chip">
                <span className="avatar sm">{initials(s.staff)}</span>
                {s.staff}
                <small>since {time(s.since)}</small>
              </span>
            ))}
            {!data.live.on_shift.length && <span className="muted">Nobody</span>}
          </div>
        </section>
      </div>

      <div className="dash-row three">
        <section className="card">
          <header className="card-head">
            <h3>Best sellers</h3>
            <button className="link-btn" onClick={() => onOpen("reports")}>
              All items
            </button>
          </header>
          <BestSellers best={data.best} />
        </section>
        <section className="card">
          <header className="card-head">
            <h3>How customers paid</h3>
          </header>
          <PaymentMix payments={data.payments} />
        </section>
        <section className="card">
          <header className="card-head">
            <h3>Waiters</h3>
            <button className="link-btn" onClick={() => onOpen("shifts")}>
              Shifts
            </button>
          </header>
          <div className="waiters">
            {data.by_waiter.map((w, i) => (
              <div key={w.waiter} className="waiter-row">
                <span className={`avatar ${i === 0 ? "gold" : ""}`}>{initials(w.waiter)}</span>
                <span className="grow">
                  {w.waiter}
                  <small className="muted"> · {w.bills} bills</small>
                  <span className="meter thin">
                    <span style={{ width: `${(w.sales / Math.max(1, data.by_waiter[0].sales)) * 100}%` }} />
                  </span>
                </span>
                <strong>{formatKsh(w.sales)}</strong>
              </div>
            ))}
            {!data.by_waiter.length && <p className="muted">No bills finished yet.</p>}
          </div>
        </section>
      </div>

      <div className="dash-row three">
        <section className="card">
          <header className="card-head">
            <h3>Needs a look</h3>
          </header>
          <div className="alerts">
            {data.alerts.map((a) => (
              <p key={a.text} className={`alert ${a.tone}`}>
                {a.tone === "bad" ? <OctagonAlert size={20} /> : <TriangleAlert size={20} />}
                {a.text}
              </p>
            ))}
            {!data.alerts.length && (
              <p className="alert good">
                <CheckCircle2 size={20} /> All clear: no shortages, removals, free items or stock problems.
              </p>
            )}
          </div>
        </section>
        <section className="card">
          <header className="card-head">
            <h3>Latest bills</h3>
            <button className="link-btn" onClick={() => onOpen("bills")}>
              All bills
            </button>
          </header>
          <div className="recent">
            {data.recent.map((r) => (
              <div key={r.number} className="recent-row">
                <span className="recent-no">#{String(r.number).padStart(4, "0")}</span>
                <span className="grow">
                  {r.place}
                  <small className="muted">
                    {" "}
                    · {r.waiter} · {time(r.closed_at)}
                  </small>
                </span>
                <span className={`pay-pill ${r.paid_by.split("+")[0]}`}>{r.paid_by.split("+").map((m) => METHOD[m] ?? m).join(" + ")}</span>
                <strong>{formatKsh(r.total)}</strong>
              </div>
            ))}
            {!data.recent.length && <p className="muted">No bills finished yet.</p>}
          </div>
        </section>
        <section className="card">
          <header className="card-head">
            <h3>Sales by category</h3>
          </header>
          <BarList rows={data.by_category.map((c) => ({ label: c.category, value: c.sales }))} />
        </section>
      </div>
    </div>
  );
}

export function BestSellers({ best }: { best: Data["best"] }) {
  if (!best.length) return <p className="muted">Nothing sold yet today.</p>;
  return (
    <div className="best">
      {best.map((b, i) => (
        <div key={b.item} className="best-row">
          <span className="best-rank">{i + 1}</span>
          {b.image ? <img src={b.image} alt="" /> : <span className="best-img">{initials(b.item)}</span>}
          <span className="grow best-name">
            {b.item}
            <small>{b.quantity} sold</small>
          </span>
          <strong>{formatKsh(b.sales)}</strong>
        </div>
      ))}
    </div>
  );
}

export function Kpi({ label, value, now, then, lastDay, big }: { label: string; value: string; now: number; then: number; lastDay: string; big?: boolean }) {
  const change = then ? Math.round(((now - then) / then) * 100) : null;
  return (
    <div className={`kpi ${big ? "kpi-big" : ""}`}>
      <span className="kpi-label">{label}</span>
      <strong className="kpi-value">{value}</strong>
      {change === null ? (
        <span className="kpi-note">{now ? `Nothing ${lastDay} by now` : "Nothing yet"}</span>
      ) : (
        <span className={`delta ${change >= 0 ? "up" : "down"}`}>
          {change >= 0 ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
          {Math.abs(change)}% vs {lastDay}
        </span>
      )}
    </div>
  );
}

/** Today's sales per hour as bars, last week's same day as quieter bars beside them.
 * One axis, from the first busy hour to now (or the last sale). */
export function HourChart({ data, compact }: { data: Data; compact?: boolean }) {
  const { today, last_week } = data.by_hour;
  if (!today.some(Boolean) && !last_week.some(Boolean))
    return <p className="chart-empty muted">No sales yet today. The bars appear as orders are paid.</p>;
  const busy = today.map((v, i) => (v || last_week[i] ? i : -1)).filter((i) => i >= 0);
  let first = Math.min(busy[0] ?? data.now_slot, data.now_slot);
  let last = Math.max(busy[busy.length - 1] ?? data.now_slot, data.now_slot);
  while (last - first < 7) first > 0 ? first-- : last++;
  const slots = Array.from({ length: last - first + 1 }, (_, i) => first + i);
  const max = Math.max(100, ...slots.map((s) => Math.max(today[s], last_week[s])));
  const nice = niceMax(max);
  const W = compact ? 360 : 640, H = compact ? 190 : 200, left = compact ? 40 : 52, bottom = 24, top = 8;
  const plotW = W - left - 8, plotH = H - bottom - top;
  const step = plotW / slots.length;
  const bar = Math.min(18, step * 0.32);
  const y = (v: number) => top + plotH - (v / nice) * plotH;
  const hour = (s: number) => String((data.cutoff_hour + s) % 24).padStart(2, "0");
  return (
    <svg className={`hour-chart ${compact ? "compact" : ""}`} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Sales by hour, today and last week">
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={left} x2={W - 8} y1={y(nice * f)} y2={y(nice * f)} className="grid" />
          <text x={left - 8} y={y(nice * f) + 4} className="axis" textAnchor="end">
            {short(nice * f)}
          </text>
        </g>
      ))}
      {slots.map((s, i) => {
        const x = left + i * step + step / 2;
        const tip = `${hour(s)}:00 – today ${formatKsh(today[s])}, last week ${formatKsh(last_week[s])}`;
        return (
          <g key={s} className={`slot ${s === data.now_slot ? "now" : ""}`}>
            <title>{tip}</title>
            <rect x={x - step / 2} y={top} width={step} height={plotH} className="hit" />
            {last_week[s] > 0 && <path d={roundTop(x - bar - 1, y(last_week[s]), bar, top + plotH - y(last_week[s]))} className="b-before" />}
            {today[s] > 0 && <path d={roundTop(x + 1, y(today[s]), bar, top + plotH - y(today[s]))} className="b-today" />}
            <text x={x} y={H - 6} className={`axis ${s === data.now_slot ? "axis-now" : ""}`} textAnchor="middle">
              {s === data.now_slot ? "now" : hour(s)}
            </text>
          </g>
        );
      })}
      <line x1={left} x2={W - 8} y1={top + plotH} y2={top + plotH} className="base" />
    </svg>
  );
}

/** A bar with 4px rounded top corners, square at the baseline. */
function roundTop(x: number, y: number, w: number, h: number) {
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function niceMax(v: number) {
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((n) => n >= v) ?? v;
}

const short = (v: number) => (v >= 1000 ? `${+(v / 1000).toFixed(1)}k` : String(Math.round(v)));

export function PaymentMix({ payments }: { payments: Data["payments"] }) {
  const rows = (Object.keys(METHOD) as (keyof Data["payments"])[]).map((k) => ({ key: k, value: payments[k] })).filter((r) => r.value > 0);
  const total = rows.reduce((s, r) => s + r.value, 0);
  if (!total) return <p className="muted">No payments yet today.</p>;
  return (
    <>
      <div className="mix-bar" role="img" aria-label="Share of sales by payment method">
        {rows.map((r) => (
          <span key={r.key} className={`mix-${r.key}`} style={{ flexGrow: r.value }} title={`${METHOD[r.key]}: ${formatKsh(r.value)}`} />
        ))}
      </div>
      <div className="mix-legend">
        {rows.map((r) => (
          <div key={r.key} className="mix-row">
            <i className={`sw mix-${r.key}`} />
            <span className="grow">{METHOD[r.key]}</span>
            <span className="muted">{Math.round((r.value / total) * 100)}%</span>
            <strong>{formatKsh(r.value)}</strong>
          </div>
        ))}
      </div>
    </>
  );
}

