import { useEffect, useState } from "react";
import {
  ApiError,
  closeEmpty,
  getFloor,
  handOver,
  mergeBill,
  moveBill,
  reprint,
  splitBill,
  voidLine,
  type Bill,
  type Floor,
  type Session,
  type Ticket,
} from "../services/api";
import { ApprovalDialog } from "../shared/ApprovalDialog";
import { Keypad } from "../shared/Keypad";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";
import { groupLines, type LineGroup } from "./billLines";

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");

const REASONS = [
  { value: "not_prepared", label: "Not prepared", hint: "goes back to stock" },
  { value: "already_prepared", label: "Already prepared / poured", hint: "recorded as waste" },
] as const;

/** Remove one unit of an item already sent. Waiters need an Owner or Supervisor PIN,
 * who picks why: not prepared (back to stock) or already prepared (waste). */
export function VoidDialog({
  session,
  bill,
  group,
  onDone,
  onClose,
}: {
  session: Session;
  bill: Bill;
  group: LineGroup;
  onDone: (bill: Bill) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState<(typeof REASONS)[number] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const needsApproval = session.permissions.void_item === "approval";
  const line = group.lines[group.lines.length - 1];

  const submit = async (approvalId?: string) => {
    try {
      onDone(await voidLine(bill.id, line.id, reason!.value, approvalId));
    } catch (e) {
      setError(errorText(e));
      setReason(null);
    }
  };

  if (reason && needsApproval) {
    return (
      <ApprovalDialog
        action="void_item"
        what={`Remove 1 × ${group.name} from ${bill.place} (${reason.label.toLowerCase()})`}
        requestedBy={session.staff.name}
        reason={reason.label}
        onApproved={submit}
        onCancel={() => setReason(null)}
      />
    );
  }

  return (
    <Modal title={`Remove 1 × ${group.name}?`} onClose={onClose}>
      <p className="muted" style={{ margin: 0, fontSize: 18 }}>
        Already sent at {formatKsh(group.unitPrice)}. Why is it being removed?
      </p>
      <div className="choice-list">
        {REASONS.map((r) => (
          <button
            key={r.value}
            className="choice"
            onClick={() => {
              setReason(r);
              if (!needsApproval) {
                voidLine(bill.id, line.id, r.value).then(onDone, (e) => (setError(errorText(e)), setReason(null)));
              }
            }}
          >
            <span>{r.label}</span>
            <small>{r.hint}</small>
          </button>
        ))}
      </div>
      <p className="error-text" role="alert">
        {error ?? ""}
      </p>
    </Modal>
  );
}

type Panel = "menu" | "move" | "handover" | "split" | "merge" | "reprint";

export function MoreMenu({
  session,
  bill,
  onChanged,
  onOpen,
  onClosed,
  onClose,
}: {
  session: Session;
  bill: Bill;
  onChanged: (bill: Bill) => void;
  onOpen: (billId: string) => void;
  onClosed: () => void;
  onClose: () => void;
}) {
  const [panel, setPanel] = useState<Panel>("menu");
  const [error, setError] = useState<string | null>(null);
  const run = (p: Promise<Bill>, then: (b: Bill) => void = onChanged) => p.then(then, (e) => setError(errorText(e)));
  const open = bill.status === "open";
  const empty = bill.total === 0 && bill.paid === 0;

  const body = () => {
    switch (panel) {
      case "move":
        return <MovePanel onPick={(tableId) => run(moveBill(bill.id, tableId))} />;
      case "handover":
        return <HandoverPanel onPin={(pin) => run(handOver(bill.id, pin), onClosed)} error={error} />;
      case "split":
        return <SplitPanel bill={bill} onSplit={(ids) => run(splitBill(bill.id, ids), (b) => onOpen(b.id))} />;
      case "merge":
        return <MergePanel bill={bill} onPick={(fromId) => run(mergeBill(bill.id, fromId))} />;
      case "reprint":
        return <ReprintPanel session={session} bill={bill} onDone={onChanged} onError={setError} />;
      default:
        return (
          <div className="choice-list">
            {open && <Choice label="Move to another table" onClick={() => setPanel("move")} />}
            {open && <Choice label="Hand over to another waiter" onClick={() => setPanel("handover")} />}
            {open && bill.lines.some((l) => !l.voided) && <Choice label="Split bill by items" onClick={() => setPanel("split")} />}
            {open && <Choice label="Merge another of my bills into this one" onClick={() => setPanel("merge")} />}
            <Choice label="Reprint a slip, ticket or receipt" onClick={() => setPanel("reprint")} />
            {open && empty && <Choice label="Close this empty bill" onClick={() => run(closeEmpty(bill.id), onClosed)} />}
          </div>
        );
    }
  };

  const titles: Record<Panel, string> = {
    menu: `${bill.place} · More`,
    move: "Move to which table?",
    handover: "Hand over",
    split: "Split: move items to a new bill",
    merge: "Merge which bill into this one?",
    reprint: "Reprint",
  };

  return (
    <Modal title={titles[panel]} onClose={panel === "menu" ? onClose : () => (setPanel("menu"), setError(null))} wide={panel !== "menu"}>
      {body()}
      {panel !== "handover" && (
        <p className="error-text" role="alert">
          {error ?? ""}
        </p>
      )}
    </Modal>
  );
}

function Choice({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button className="choice" onClick={onClick}>
      <span>{label}</span>
      <small>›</small>
    </button>
  );
}

function useFloor() {
  const [floor, setFloor] = useState<Floor | null>(null);
  useEffect(() => {
    getFloor().then(setFloor, () => {});
  }, []);
  return floor;
}

function MovePanel({ onPick }: { onPick: (tableId: string) => void }) {
  const floor = useFloor();
  if (!floor) return <p className="muted">Loading…</p>;
  const busy = new Set(floor.bills.map((b) => b.table_id));
  const free = floor.tables.filter((t) => !busy.has(t.id));
  return (
    <div className="choice-grid">
      {free.map((t) => (
        <button key={t.id} className="choice" onClick={() => onPick(t.id)}>
          {t.name}
        </button>
      ))}
      {!free.length && <p className="muted">No free tables.</p>}
    </div>
  );
}

function HandoverPanel({ onPin, error }: { onPin: (pin: string) => void; error: string | null }) {
  const [pin, setPin] = useState("");
  return (
    <>
      <p style={{ margin: 0, fontSize: 18 }}>
        <strong>Receiving waiter:</strong> enter your PIN to accept this bill. Its money will be yours.
      </p>
      <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
        <Keypad value={pin} onChange={setPin} onEnter={() => (onPin(pin), setPin(""))} enterLabel="ACCEPT" />
        <div style={{ fontSize: 28, letterSpacing: 8 }}>{"•".repeat(pin.length)}</div>
      </div>
      <p className="error-text" role="alert">
        {error ?? ""}
      </p>
    </>
  );
}

function SplitPanel({ bill, onSplit }: { bill: Bill; onSplit: (lineIds: string[]) => void }) {
  const groups = groupLines(bill.lines).filter((g) => g.lines.length);
  const [picked, setPicked] = useState<Record<string, number>>({});
  const ids = groups.flatMap((g) => g.lines.slice(0, picked[g.key] ?? 0).map((l) => l.id));
  const amount = groups.reduce((s, g) => s + (picked[g.key] ?? 0) * g.unitPrice, 0);
  const step = (g: LineGroup, d: number) =>
    setPicked({ ...picked, [g.key]: Math.max(0, Math.min(g.lines.length, (picked[g.key] ?? 0) + d)) });
  return (
    <>
      <div className="choice-list">
        {groups.map((g) => (
          <div key={g.key} className="split-row">
            <span className="grow">
              {g.lines.length}× {g.name} {g.note && <span className="line-note">"{g.note}"</span>}
            </span>
            <button className="step" onClick={() => step(g, -1)}>
              −
            </button>
            <span className="qty">{picked[g.key] ?? 0}</span>
            <button className="step" onClick={() => step(g, 1)}>
              +
            </button>
          </div>
        ))}
      </div>
      <div className="row row-end">
        <span className="grow muted">New bill: {formatKsh(amount)}</span>
        <button className="btn btn-primary" disabled={!ids.length} onClick={() => onSplit(ids)}>
          MOVE TO NEW BILL
        </button>
      </div>
    </>
  );
}

function MergePanel({ bill, onPick }: { bill: Bill; onPick: (fromId: string) => void }) {
  const floor = useFloor();
  if (!floor) return <p className="muted">Loading…</p>;
  const others = floor.bills.filter((b) => b.id !== bill.id && b.waiter.id === bill.waiter.id);
  return (
    <div className="choice-list">
      {others.map((b) => (
        <button key={b.id} className="choice" onClick={() => onPick(b.id)}>
          <span>
            {b.place} · #{String(b.number).padStart(4, "0")}
          </span>
          <small>{formatKsh(b.total ?? 0)}</small>
        </button>
      ))}
      {!others.length && <p className="muted">{bill.waiter.name} has no other open bills.</p>}
    </div>
  );
}

const KIND = { bar_slip: "Bar slip", kitchen_ticket: "Kitchen ticket", bill: "Bill", receipt: "Receipt" } as const;

function ReprintPanel({
  session,
  bill,
  onDone,
  onError,
}: {
  session: Session;
  bill: Bill;
  onDone: (bill: Bill) => void;
  onError: (message: string) => void;
}) {
  const [asking, setAsking] = useState<Ticket | null>(null);
  const tickets = bill.tickets.filter((t) => t.kind !== "bill");
  const needsApproval = (t: Ticket) => t.printed_at !== null && session.permissions.reprint_receipt === "approval";
  const go = (t: Ticket, approvalId?: string) =>
    reprint(t.id, approvalId).then(onDone, (e) => onError(errorText(e)));

  if (asking) {
    return (
      <ApprovalDialog
        action="reprint_receipt"
        what={`Reprint ${KIND[asking.kind]} ${asking.number} for ${bill.place}`}
        requestedBy={session.staff.name}
        reason="Reprint"
        onApproved={(id) => (setAsking(null), go(asking, id))}
        onCancel={() => setAsking(null)}
      />
    );
  }
  return (
    <div className="choice-list">
      {tickets.map((t) => (
        <button key={t.id} className="choice" onClick={() => (needsApproval(t) ? setAsking(t) : go(t))}>
          <span>
            {KIND[t.kind]} {t.number} ·{" "}
            {new Date(t.created_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
          </span>
          <small className={t.status === "not_printed" ? "warn" : ""}>
            {t.status === "not_printed" ? "Not printed" : needsApproval(t) ? "Needs approval" : "Printed"}
          </small>
        </button>
      ))}
      {!tickets.length && <p className="muted">Nothing printed yet.</p>}
    </div>
  );
}
