import { useCallback, useEffect, useState, type ReactNode } from "react";
import { formatKsh } from "../shared/money";
import { BarList, Big, ClosingView, ProfitBlock, Row, SalesBlock, Section } from "../shared/ReportParts";
import {
  getClosing,
  getDebtors,
  getProfit,
  getStock,
  getToday,
  login,
  PhoneError,
  savedToken,
  saveToken,
  setLoggedOutHandler,
  type PhoneClosing,
  type PhoneDebtors,
  type PhoneProfit,
  type PhoneStock,
  type Today,
} from "./api";
import "./phone.css";

type Tab = "today" | "closing" | "stock" | "profit" | "debtors";
const TABS: [Tab, string][] = [["today", "Today"], ["closing", "Closing"], ["stock", "Stock"], ["profit", "Profit"], ["debtors", "Debtors"]];
const message = (e: unknown) => (e instanceof PhoneError ? e.message : "Something went wrong.");

/** The owner's phone (masterplan 4.10): read-only, from the cloud copy. */
export function PhoneApp() {
  const [loggedIn, setLoggedIn] = useState(() => savedToken() !== null);
  const [tab, setTab] = useState<Tab>("today");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => setLoggedOutHandler(() => setLoggedIn(false)), []);

  if (!loggedIn) return <Login onDone={() => setLoggedIn(true)} />;
  return (
    <div className="ph">
      <main className="ph-main" key={refresh}>
        {tab === "today" && <TodayView />}
        {tab === "closing" && <ClosingPage />}
        {tab === "stock" && <StockView />}
        {tab === "profit" && <ProfitView />}
        {tab === "debtors" && <DebtorsView />}
      </main>
      <nav className="ph-nav">
        {TABS.map(([t, label]) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => (tab === t ? setRefresh(refresh + 1) : setTab(t))}>
            {label}
          </button>
        ))}
      </nav>
    </div>
  );
}

function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      saveToken((await login(email, password, code)).token);
      onDone();
    } catch (err) {
      setError(message(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="ph-login" onSubmit={submit}>
      <h1>Faida</h1>
      <p className="ph-muted">Owner login</p>
      <label>
        Email
        <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </label>
      <label>
        Password
        <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </label>
      <label>
        Code from your authenticator app
        <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />
      </label>
      <p className="ph-error" role="alert">
        {error ?? ""}
      </p>
      <button className="ph-button" disabled={busy || code.length !== 6}>
        Log in
      </button>
    </form>
  );
}

function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(load, deps);
  useEffect(() => {
    setData(null);
    run().then(setData, (e) => setError(message(e)));
  }, [run]);
  return { data, error };
}

function Header({ title, updated, children }: { title: string; updated: string | null; children?: ReactNode }) {
  const at = updated ? new Date(updated) : null;
  const stale = !at || Date.now() - at.getTime() > 60 * 60 * 1000;
  return (
    <header className="ph-header">
      <div>
        <h1>{title}</h1>
        <p className={stale ? "ph-updated stale" : "ph-updated"}>
          {at ? `Last updated ${at.toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" })}` : "Not synced yet"}
        </p>
      </div>
      {children}
    </header>
  );
}

const Loading = ({ error }: { error: string | null }) => <p className={error ? "ph-error ph-pad" : "ph-muted ph-pad"}>{error ?? "Loading…"}</p>;

function TodayView() {
  const { data: t, error } = useLoad<Today>(getToday);
  if (!t) return <Loading error={error} />;
  return (
    <>
      <Header title={t.business_name} updated={t.last_updated}>
        <button className="ph-link" onClick={() => (saveToken(null), location.reload())}>
          Log out
        </button>
      </Header>
      <p className="ph-muted ph-pad">
        Business day {new Date(`${t.day}T12:00:00`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}
        {t.closed ? " · closed" : t.open_shifts.length ? ` · open: ${t.open_shifts.join(", ")}` : ""}
      </p>
      {t.alerts.length > 0 && (
        <div className="ph-alerts">
          {t.alerts.map((a) => (
            <p key={a}>⚠ {a}</p>
          ))}
        </div>
      )}
      <div className="ph-pad">
        <div className="rp-bigs">
          <Big label="Sales" value={formatKsh(t.sales.total)} />
          <Big label="Cash" value={formatKsh(t.sales.cash)} />
          <Big label="M-Pesa" value={formatKsh(t.sales.mpesa)} />
          <Big label="Credit" value={formatKsh(t.sales.credit)} />
        </div>
        <Section title="Today">
          <Row label="Bills" value={t.sales.bills} />
          <Row label="Credit collected" value={formatKsh(t.credit_collected.total)} />
          <Row label="Items removed after sending" value={`${t.voids.count} · ${formatKsh(t.voids.total)}`} tone={t.voids.count ? "warn" : undefined} />
          {t.shortages.map((s) => (
            <Row key={s.staff} label={`${s.staff} short`} value={formatKsh(-s.difference)} tone="bad" />
          ))}
          {t.sales.unpaid > 0 && <Row label="Unpaid (waiter responsible)" value={formatKsh(t.sales.unpaid)} tone="warn" />}
        </Section>
        {(t.low_stock.length > 0 || t.check_stock.length > 0) && (
          <Section title="Stock to check">
            {t.check_stock.map((s) => (
              <Row key={s.item} label={`${s.item} (below zero)`} value={s.level} tone="bad" />
            ))}
            {t.low_stock.map((s) => (
              <Row key={s.item} label={s.item} value={s.level} tone="warn" />
            ))}
          </Section>
        )}
      </div>
    </>
  );
}

function ClosingPage() {
  const [day, setDay] = useState<string | undefined>(undefined);
  const { data: c, error } = useLoad<PhoneClosing>(() => getClosing(day), [day]);
  if (!c) return <Loading error={error} />;
  const move = (n: number) => {
    const d = new Date(`${c.day}T12:00:00`);
    d.setDate(d.getDate() + n);
    setDay(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
  };
  return (
    <>
      <Header title="Daily closing" updated={c.last_updated} />
      <div className="ph-daybar">
        <button onClick={() => move(-1)} aria-label="Previous day">
          ‹
        </button>
        <span>
          {new Date(`${c.day}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}
          {c.closed ? " · closed" : " · so far"}
        </span>
        <button onClick={() => move(1)} aria-label="Next day">
          ›
        </button>
      </div>
      <div className="ph-pad">
        <ClosingView report={c.report} />
      </div>
    </>
  );
}

function StockView() {
  const { data: s, error } = useLoad<PhoneStock>(getStock);
  if (!s) return <Loading error={error} />;
  return (
    <>
      <Header title="Stock" updated={s.last_updated} />
      <div className="ph-pad rp">
        <Big label="Stock value (buying price)" value={formatKsh(s.value)} />
        <Section title="Below zero: count these">
          {s.check.map((i) => <Row key={i.item} label={i.item} value={i.level} tone="bad" />)}
          {!s.check.length && <p className="rp-empty">None.</p>}
        </Section>
        <Section title="Low stock">
          {s.low.map((i) => <Row key={i.item} label={i.item} value={i.level} tone="warn" />)}
          {!s.low.length && <p className="rp-empty">None.</p>}
        </Section>
        <Section title="Stock-take differences, last 30 days">
          {s.variance.map((v, i) => (
            <Row key={i} label={`${v.item}: ${v.variance}`} value={formatKsh(v.value)} tone={v.value < 0 ? "warn" : undefined} />
          ))}
          {!s.variance.length && <p className="rp-empty">None.</p>}
        </Section>
      </div>
    </>
  );
}

function ProfitView() {
  const [which, setWhich] = useState<"month" | "last">("month");
  const { data: p, error } = useLoad<PhoneProfit>(() => {
    if (which === "month") return getProfit();
    const now = new Date();
    const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const last = new Date(now.getFullYear(), now.getMonth(), 0);
    const f = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    return getProfit(f(first), f(last));
  }, [which]);
  return (
    <>
      <Header title="Profit" updated={p?.last_updated ?? null} />
      <div className="ph-daybar">
        <button className={which === "month" ? "on" : ""} onClick={() => setWhich("month")}>
          This month
        </button>
        <button className={which === "last" ? "on" : ""} onClick={() => setWhich("last")}>
          Last month
        </button>
      </div>
      {!p ? (
        <Loading error={error} />
      ) : (
        <div className="ph-pad rp">
          <Big label="Real profit" value={`${p.profit.real_profit < 0 ? "−" : ""}${formatKsh(Math.abs(p.profit.real_profit))}`} tone={p.profit.real_profit < 0 ? "bad" : "good"} />
          <Section title="How it's worked out">
            <ProfitBlock profit={p.profit} />
          </Section>
          <Section title="Sales">
            <SalesBlock sales={p.sales} />
          </Section>
          <Section title="Shortages">
            <BarList rows={p.shortages.filter((s) => s.short).map((s) => ({ label: s.staff, value: s.short, note: `${s.times_short}×` }))} />
          </Section>
        </div>
      )}
    </>
  );
}

function DebtorsView() {
  const { data: d, error } = useLoad<PhoneDebtors>(getDebtors);
  if (!d) return <Loading error={error} />;
  return (
    <>
      <Header title="Debtors" updated={d.last_updated} />
      <div className="ph-pad rp">
        <Big label="Owed to you" value={formatKsh(d.total)} />
        <Section title="Oldest first">
          {d.debtors.map((x) => (
            <Row
              key={x.name}
              label={
                <>
                  {x.name}
                  {x.phone && (
                    <>
                      {" · "}
                      <a href={`tel:${x.phone}`}>{x.phone}</a>
                    </>
                  )}
                  <br />
                  <small className="ph-muted">{x.since ? `since ${new Date(x.since).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}` : ""}</small>
                </>
              }
              value={formatKsh(x.owed)}
            />
          ))}
          {!d.debtors.length && <p className="rp-empty">Nobody owes you.</p>}
        </Section>
      </div>
    </>
  );
}
