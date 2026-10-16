import { Armchair, Clock3, LayoutDashboard, LayoutGrid, LogOut, Plus, Printer, ReceiptText, Search, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, getFloor, openBill, type Floor, type FloorBill, type Session } from "../services/api";
import { initials, since } from "../shared/look";
import { formatKsh } from "../shared/money";

type Props = {
  session: Session;
  onOpen: (billId: string) => void;
  onNavigate: (screen: "endShift" | "myBills" | "owner" | "floor") => void;
  onLock: () => void;
};

function greeting(now: Date) {
  const h = now.getHours();
  return h < 12 && h >= 5 ? "Good morning" : h < 17 && h >= 12 ? "Good afternoon" : "Good evening";
}

const no = (n: number) => `#${String(n).padStart(4, "0")}`;
const hasTable = (b: FloorBill) => Boolean(b.table_id || b.table_label);

/** The waiter's home (like Square's and Toast's open orders): their own open orders as
 * big cards, and NEW ORDER. An order is known by its number; a table is optional and can
 * be any number, so it works with 10 tables, 1000, or customers standing at the bar.
 * Supervisors and the owner can also see everyone's orders. */
export function HomeScreen({ session, onOpen, onNavigate, onLock }: Props) {
  const [floor, setFloor] = useState<Floor | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [everyone, setEveryone] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const seesAll = session.permissions.view_other_bills === "allow";

  useEffect(() => {
    getFloor().then(setFloor, (e) => setError(e.message));
    const tick = setInterval(() => setNow(Date.now()), 30_000);
    const refresh = setInterval(() => getFloor().then(setFloor, () => {}), 20_000);
    return () => (clearInterval(tick), clearInterval(refresh));
  }, []);

  const newOrder = async () => {
    setBusy(true);
    try {
      onOpen((await openBill()).id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setBusy(false);
    }
  };

  if (!floor) return <main className="screen screen-loading"><span className="spinner" /> Loading orders…</main>;

  const mine = floor.bills.filter((b) => b.mine);
  const shown = (everyone && seesAll ? floor.bills : mine)
    .filter((b) => {
      const q = search.trim().toLowerCase().replace(/^#0*/, "");
      if (!q) return true;
      return String(b.number).includes(q) || b.place.toLowerCase().includes(q) || (b.table_label ?? "").toLowerCase() === q;
    })
    .sort((a, b) => b.number - a.number);
  const myAmount = mine.reduce((s, b) => s + (b.balance ?? 0), 0);
  const unprinted = mine.filter((b) => b.not_printed).length;

  return (
    <main className="screen home">
      <div className="screen-scroll">
        <header className="home-head rise">
          <div>
            <h1>
              {greeting(new Date(now))}, {session.staff.name.split(" ")[0]}
            </h1>
            <p className="muted">Tap NEW ORDER to start. Add a table only if they're seated.</p>
          </div>
          <div className="stat-chips">
            <div className="stat">
              <span>My open orders</span>
              <strong>{mine.length}</strong>
            </div>
            <div className="stat">
              <span>Still to collect</span>
              <strong>{formatKsh(myAmount)}</strong>
            </div>
            {unprinted > 0 && (
              <div className="stat warn-stat">
                <span>Not printed</span>
                <strong>{unprinted}</strong>
              </div>
            )}
          </div>
        </header>

        <div className="home-actions">
          <button className="new-order" onClick={newOrder} disabled={busy}>
            <span className="new-order-icon">
              <Plus size={34} strokeWidth={2.6} />
            </span>
            <span>
              NEW ORDER
              <small>Numbered automatically</small>
            </span>
          </button>
          <label className="search-box home-search">
            <Search size={22} />
            <input className="text-input" inputMode="search" placeholder="Find an order or table, e.g. 31 or 57" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
        </div>

        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}

        <div className="section-bar">
          <h2 className="section-title">{everyone ? "All open orders" : "My open orders"}</h2>
          <span className="grow" />
          {seesAll && (
            <div className="segmented">
              <button className={everyone ? "" : "on"} onClick={() => setEveryone(false)}>
                Mine
              </button>
              <button className={everyone ? "on" : ""} onClick={() => setEveryone(true)}>
                Everyone
              </button>
            </div>
          )}
        </div>

        <div className="order-grid">
          {shown.map((b, i) => {
            const old = (now - new Date(b.opened_at).getTime()) / 60000;
            return (
              <button
                key={b.id}
                className={`order-card ${b.mine ? "mine" : "others"} ${b.not_printed ? "attention" : ""}`}
                onClick={() => onOpen(b.id)}
                disabled={b.total === null}
                style={{ animationDelay: `${Math.min(i, 12) * 20}ms` }}
              >
                <span className="order-top">
                  <span className="order-no">{no(b.number)}</span>
                  {b.not_printed && <Printer size={20} className="table-alert" />}
                </span>
                <span className={`order-place ${hasTable(b) ? "" : "standing"}`}>
                  {hasTable(b) ? (
                    <>
                      <Armchair size={16} /> {b.place}
                    </>
                  ) : (
                    "No table"
                  )}
                </span>
                <span className="order-amount">{b.balance === null ? "" : formatKsh(b.balance)}</span>
                <span className="table-foot">
                  <span className="table-waiter">
                    <span className="avatar sm">{initials(b.waiter.name)}</span>
                    {b.mine ? "Mine" : b.waiter.name}
                  </span>
                  <span className={`table-time ${old >= 120 ? "very-long" : old >= 60 ? "long" : "fresh"}`}>
                    <Clock3 size={14} /> {since(b.opened_at, now)}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
        {!shown.length && (
          <div className="empty-state">
            <ReceiptText size={48} />
            {search ? `No open order matches "${search}".` : "No open orders. Tap NEW ORDER when a customer orders."}
          </div>
        )}
      </div>
      <footer className="screen-actions">
        <button className="btn btn-quiet" onClick={() => onNavigate("myBills")}>
          <ReceiptText size={20} /> Finished
        </button>
        <button className="btn btn-quiet" onClick={() => onNavigate("floor")}>
          <LayoutGrid size={20} /> Floor plan
        </button>
        {session.permissions.receive_handover === "allow" && (
          <button className="btn btn-quiet" onClick={() => onNavigate("owner")}>
            <LayoutDashboard size={20} /> Owner area
          </button>
        )}
        <span className="grow" />
        <button className="btn" onClick={() => onNavigate("endShift")}>
          <Wallet size={20} /> END MY SHIFT
        </button>
        <button className="btn btn-primary" onClick={onLock}>
          <LogOut size={20} /> LOCK
        </button>
      </footer>
    </main>
  );
}
