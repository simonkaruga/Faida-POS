import {
  Armchair,
  Clock3,
  LayoutDashboard,
  Lock,
  LogOut,
  Plus,
  Printer,
  ReceiptText,
  UserRound,
  Wallet,
} from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, getFloor, openBill, type Floor, type FloorBill, type Session } from "../services/api";
import { initials, since } from "../shared/look";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";

type Props = {
  session: Session;
  onOpen: (billId: string) => void;
  onNavigate: (screen: "endShift" | "myBills" | "owner") => void;
  onLock: () => void;
};

type Filter = "all" | "mine" | "free";

function greeting(now: Date) {
  const h = now.getHours();
  return h < 12 && h >= 5 ? "Good morning" : h < 17 && h >= 12 ? "Good afternoon" : "Good evening";
}

/** Minutes a bill has been open, coloured like Square's floor plan: calm, then orange
 * after an hour, red after two. */
function age(opened: string, now: number): "fresh" | "long" | "very-long" {
  const minutes = (now - new Date(opened).getTime()) / 60000;
  return minutes >= 120 ? "very-long" : minutes >= 60 ? "long" : "fresh";
}

/** The waiter's home screen (masterplan 9.4): free tables, mine in blue with the
 * amount and how long it's been open, other waiters' tables locked, then tabs. */
export function TablesScreen({ session, onOpen, onNavigate, onLock }: Props) {
  const [floor, setFloor] = useState<Floor | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newTab, setNewTab] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    getFloor().then(setFloor, (e) => setError(e.message));
    const tick = setInterval(() => setNow(Date.now()), 30_000);
    const refresh = setInterval(() => getFloor().then(setFloor, () => {}), 20_000);
    return () => (clearInterval(tick), clearInterval(refresh));
  }, []);

  const start = async (place: { table_id: string } | { tab_name: string }) => {
    try {
      onOpen((await openBill(place)).id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      getFloor().then(setFloor, () => {});
    }
  };

  if (!floor) return <main className="screen screen-loading"><span className="spinner" /> Loading tables…</main>;

  const byTable = new Map(floor.bills.filter((b) => b.table_id).map((b) => [b.table_id!, b]));
  const tabs = floor.bills.filter((b) => !b.table_id);
  const mine = floor.bills.filter((b) => b.mine);
  const myAmount = mine.reduce((s, b) => s + (b.balance ?? 0), 0);
  const free = floor.tables.filter((t) => !byTable.has(t.id)).length;
  const unprinted = floor.bills.filter((b) => b.not_printed).length;
  const show = (bill: FloorBill | undefined) => filter === "all" || (filter === "mine" ? bill?.mine : !bill);

  const tile = (bill: FloorBill | undefined, label: string, onFree?: () => void, i = 0) => {
    if (!bill) {
      return (
        <button key={label} className="table-tile free" onClick={onFree} style={{ animationDelay: `${i * 18}ms` }}>
          <span className="table-top">
            <span className="table-name">{label}</span>
            <Armchair size={20} className="table-icon" />
          </span>
          <span className="table-sub">Free · tap to open</span>
        </button>
      );
    }
    const locked = bill.total === null;
    const kind = locked ? "locked" : bill.mine ? "mine" : "others";
    return (
      <button
        key={bill.id}
        className={`table-tile ${kind} ${bill.not_printed ? "attention" : ""}`}
        onClick={() => !locked && onOpen(bill.id)}
        disabled={locked}
        style={{ animationDelay: `${i * 18}ms` }}
      >
        <span className="table-top">
          <span className="table-name">{label}</span>
          {bill.not_printed ? <Printer size={20} className="table-alert" /> : locked ? <Lock size={18} className="table-icon" /> : null}
        </span>
        {!locked && <span className="table-amount">{formatKsh(bill.balance ?? 0)}</span>}
        <span className="table-foot">
          <span className="table-waiter">
            <span className="avatar sm">{initials(bill.waiter.name)}</span>
            {bill.mine ? "Mine" : bill.waiter.name}
          </span>
          <span className={`table-time ${age(bill.opened_at, now)}`}>
            <Clock3 size={14} /> {since(bill.opened_at, now)}
          </span>
        </span>
      </button>
    );
  };

  return (
    <main className="screen tables">
      <div className="screen-scroll">
        <header className="tables-head rise">
          <div>
            <h1>
              {greeting(new Date(now))}, {session.staff.name.split(" ")[0]}
            </h1>
            <p className="muted">Tap a free table to start an order.</p>
          </div>
          <div className="stat-chips">
            <div className="stat">
              <span>My open bills</span>
              <strong>{mine.length}</strong>
            </div>
            <div className="stat">
              <span>My open amount</span>
              <strong>{formatKsh(myAmount)}</strong>
            </div>
            <div className="stat">
              <span>Tables free</span>
              <strong>
                {free}/{floor.tables.length}
              </strong>
            </div>
            {unprinted > 0 && (
              <div className="stat warn-stat">
                <span>Not printed</span>
                <strong>{unprinted}</strong>
              </div>
            )}
          </div>
        </header>

        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}

        <div className="section-bar">
          <h2 className="section-title">Tables</h2>
          <div className="segmented">
            {(["all", "mine", "free"] as Filter[]).map((f) => (
              <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
                {f === "all" ? "All" : f === "mine" ? "Mine" : "Free"}
              </button>
            ))}
          </div>
        </div>
        <div className="table-grid">
          {floor.tables.filter((t) => show(byTable.get(t.id))).map((t, i) => tile(byTable.get(t.id), t.name, () => start({ table_id: t.id }), i))}
        </div>

        <div className="section-bar">
          <h2 className="section-title">Tabs</h2>
        </div>
        <div className="table-grid">
          {tabs.filter((b) => filter !== "free" && show(b)).map((b, i) => tile(b, b.tab_name ?? b.place, undefined, i))}
          <button className="table-tile new-tab" onClick={() => setNewTab("")}>
            <Plus size={28} />
            <span className="table-name">New tab</span>
          </button>
        </div>
      </div>
      <footer className="screen-actions">
        <button className="btn btn-quiet" onClick={() => onNavigate("myBills")}>
          <ReceiptText size={20} /> My bills
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

      {newTab !== null && (
        <Modal title="New tab" onClose={() => setNewTab(null)}>
          <div className="row">
            <UserRound size={26} className="muted" />
            <input
              className="text-input grow"
              autoFocus
              placeholder="Customer name, e.g. Kamau"
              value={newTab}
              maxLength={40}
              onChange={(e) => setNewTab(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && newTab.trim() && start({ tab_name: newTab.trim() })}
            />
          </div>
          <div className="row row-end">
            <button className="btn btn-primary" disabled={!newTab.trim()} onClick={() => start({ tab_name: newTab.trim() })}>
              <Plus size={22} /> OPEN TAB
            </button>
          </div>
        </Modal>
      )}
    </main>
  );
}
