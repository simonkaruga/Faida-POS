import { useEffect, useState } from "react";
import { ApiError, getFloor, openBill, type Floor, type FloorBill, type Session } from "../services/api";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";

type Props = {
  session: Session;
  onOpen: (billId: string) => void;
  onLock: () => void;
};

/** The waiter's home screen (masterplan 9.4): free tables, mine in blue with the
 * amount, other waiters' tables grey and locked, then tabs. */
export function TablesScreen({ session, onOpen, onLock }: Props) {
  const [floor, setFloor] = useState<Floor | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newTab, setNewTab] = useState<string | null>(null);

  useEffect(() => {
    getFloor().then(setFloor, (e) => setError(e.message));
  }, []);

  const start = async (place: { table_id: string } | { tab_name: string }) => {
    try {
      onOpen((await openBill(place)).id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      getFloor().then(setFloor, () => {});
    }
  };

  if (!floor) return <main className="screen-center">{error ?? "Loading…"}</main>;

  const byTable = new Map(floor.bills.filter((b) => b.table_id).map((b) => [b.table_id!, b]));
  const tabs = floor.bills.filter((b) => !b.table_id);

  const tile = (bill: FloorBill | undefined, label: string, onFree?: () => void) => {
    if (!bill) {
      return (
        <button key={label} className="table-tile free" onClick={onFree}>
          <span className="table-name">{label}</span>
          <span className="table-sub">Free</span>
        </button>
      );
    }
    const locked = bill.total === null;
    return (
      <button
        key={bill.id}
        className={`table-tile ${locked ? "locked" : bill.mine ? "mine" : "others"} ${bill.not_printed ? "attention" : ""}`}
        onClick={() => !locked && onOpen(bill.id)}
        disabled={locked}
      >
        <span className="table-name">{label}</span>
        {locked ? (
          <span className="table-sub">🔒 {bill.waiter.name}</span>
        ) : (
          <>
            <span className="table-amount">{formatKsh(bill.balance ?? 0)}</span>
            <span className="table-sub">
              {bill.mine ? "Mine" : bill.waiter.name}
              {bill.not_printed ? " · Not printed" : ""}
            </span>
          </>
        )}
      </button>
    );
  };

  return (
    <main className="screen">
      <div className="screen-scroll">
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <h2 className="section-title">Tables</h2>
        <div className="table-grid">
          {floor.tables.map((t) => tile(byTable.get(t.id), t.name, () => start({ table_id: t.id })))}
        </div>
        <h2 className="section-title">Tabs</h2>
        <div className="table-grid">
          {tabs.map((b) => tile(b, b.tab_name ?? b.place))}
          <button className="table-tile new-tab" onClick={() => setNewTab("")}>
            <span className="table-name">+ New tab</span>
          </button>
        </div>
      </div>
      <footer className="screen-actions">
        <span className="muted grow">
          {session.staff.name} · {floor.bills.filter((b) => b.mine).length} open bills
        </span>
        <button className="btn btn-primary" onClick={onLock}>
          LOCK
        </button>
      </footer>

      {newTab !== null && (
        <Modal title="New tab" onClose={() => setNewTab(null)}>
          <input
            className="text-input"
            autoFocus
            placeholder="Customer name, e.g. Kamau"
            value={newTab}
            maxLength={40}
            onChange={(e) => setNewTab(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && newTab.trim() && start({ tab_name: newTab.trim() })}
          />
          <div className="row row-end">
            <button className="btn btn-primary" disabled={!newTab.trim()} onClick={() => start({ tab_name: newTab.trim() })}>
              OPEN TAB
            </button>
          </div>
        </Modal>
      )}
    </main>
  );
}
