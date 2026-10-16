import { Gift, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
  ApiError,
  closeEmpty,
  compLine,
  discountBill,
  getFloor,
  handOver,
  mergeBill,
  reprint,
  splitBill,
  voidLine,
  type Bill,
  type CompReason,
  type Floor,
  type Session,
  type Ticket,
} from "../services/api";
import { ApprovalDialog } from "../shared/ApprovalDialog";
import { Keypad } from "../shared/Keypad";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";
import { COMP_LABEL, groupLines, type LineGroup } from "./billLines";
import { TableDialog } from "./TableDialog";

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");

const REASONS = [
  { value: "not_prepared", label: "Not prepared", hint: "goes back to stock" },
  { value: "already_prepared", label: "Already prepared / poured", hint: "recorded as waste" },
] as const;

const COMP_REASONS: { value: CompReason; hint: string }[] = [
  { value: "house", hint: "a round on the house" },
  { value: "staff_drink", hint: "for staff" },
  { value: "owner_guest", hint: "the owner's guest" },
  { value: "complaint", hint: "to settle a complaint" },
  { value: "promotion", hint: "an offer" },
];

/** Tapping a sent item: remove it (void) or give it free (comp). Both need an Owner or
 * Supervisor PIN for a waiter. A free item still came out of stock. */
export function LineActions({
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
  const [mode, setMode] = useState<"pick" | "void" | "comp">("pick");
  const [reason, setReason] = useState<CompReason | null>(null);
  const [error, setError] = useState<string | null>(null);
  const line = group.lines[group.lines.length - 1];
  const canComp = session.permissions.comp_item !== "deny" && !group.free;
  const needsApproval = session.permissions.comp_item === "approval";

  if (mode === "void") return <VoidDialog session={session} bill={bill} group={group} onDone={onDone} onClose={onClose} />;
  const giveFree = (r: CompReason, approvalId?: string) =>
    compLine(bill.id, line.id, r, approvalId).then(onDone, (e) => (setReason(null), setError(errorText(e))));
  if (reason && needsApproval) {
    return (
      <ApprovalDialog
        action="comp_item"
        what={`Give 1 × ${group.name} free (${formatKsh(group.unitPrice)}): ${COMP_LABEL[reason]}`}
        requestedBy={session.staff.name}
        reason={COMP_LABEL[reason]}
        onApproved={(id) => giveFree(reason, id)}
        onCancel={() => setReason(null)}
      />
    );
  }
  return (
    <Modal title={`1 × ${group.name}`} onClose={onClose}>
      {mode === "pick" ? (
        <div className="choice-list">
          <button className="choice" onClick={() => setMode("void")}>
            <span className="row" style={{ gap: 10 }}>
              <Trash2 size={22} /> Remove it
            </span>
            <small>not wanted, or a mistake</small>
          </button>
          {canComp && (
            <button className="choice" onClick={() => setMode("comp")}>
              <span className="row" style={{ gap: 10 }}>
                <Gift size={22} /> Give it free
              </span>
              <small>on the house, staff drink…</small>
            </button>
          )}
        </div>
      ) : (
        <>
          <p className="muted" style={{ margin: 0, fontSize: 17 }}>
            It stays on the bill at 0 and still comes out of stock. The daily closing lists it.
          </p>
          <div className="choice-list">
            {COMP_REASONS.map((r) => (
              <button key={r.value} className="choice" onClick={() => (needsApproval ? setReason(r.value) : giveFree(r.value))}>
                <span>{COMP_LABEL[r.value]}</span>
                <small>{r.hint}</small>
              </button>
            ))}
          </div>
        </>
      )}
      <p className="error-text">{error ?? ""}</p>
    </Modal>
  );
}

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

type Panel = "menu" | "move" | "handover" | "split" | "merge" | "reprint" | "discount";

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

  if (panel === "move") return <TableDialog bill={bill} onDone={(b) => (onChanged(b), onClose())} onClose={() => setPanel("menu")} />;

  const body = () => {
    switch (panel) {
      case "handover":
        return <HandoverPanel onPin={(pin) => run(handOver(bill.id, pin), onClosed)} error={error} />;
      case "split":
        return <SplitPanel bill={bill} onSplit={(ids) => run(splitBill(bill.id, ids), (b) => onOpen(b.id))} />;
      case "merge":
        return <MergePanel bill={bill} onPick={(fromId) => run(mergeBill(bill.id, fromId))} />;
      case "reprint":
        return <ReprintPanel session={session} bill={bill} onDone={onChanged} onError={setError} />;
      case "discount":
        return <DiscountPanel session={session} bill={bill} onDone={onChanged} onError={setError} />;
      default:
        return (
          <div className="choice-list">
            {open && <Choice label={bill.table_id || bill.table_label ? "Change table" : "Add a table"} onClick={() => setPanel("move")} />}
            {open && <Choice label="Hand over to another waiter" onClick={() => setPanel("handover")} />}
            {open && bill.lines.some((l) => !l.voided) && <Choice label="Split bill by items" onClick={() => setPanel("split")} />}
            {open && <Choice label="Merge another of my bills into this one" onClick={() => setPanel("merge")} />}
            {open && bill.total + bill.discount > 0 && session.permissions.discount !== "deny" && (
              <Choice label={bill.discount ? `Change discount (now −${formatKsh(bill.discount)})` : "Discount"} onClick={() => setPanel("discount")} />
            )}
            <Choice label="Reprint a slip, ticket or receipt" onClick={() => setPanel("reprint")} />
            {open && empty && <Choice label="Close this empty bill" onClick={() => run(closeEmpty(bill.id), onClosed)} />}
          </div>
        );
    }
  };

  const titles: Record<Panel, string> = {
    menu: `${bill.place} · More`,
    move: "",
    handover: "Hand over",
    split: "Split: move items to a new bill",
    merge: "Merge which bill into this one?",
    reprint: "Reprint",
    discount: `Discount on ${bill.place}`,
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

const DISCOUNT_REASONS = ["Regular customer", "Complaint", "Owner's guest", "Promotion"];

/** A discount on the whole bill: a fixed amount or a percentage. Waiters need approval. */
function DiscountPanel({
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
  const [kind, setKind] = useState<"amount" | "percent">(bill.discount_kind ?? "amount");
  const [value, setValue] = useState(bill.discount_value ? String(bill.discount_value) : "");
  const [reason, setReason] = useState(DISCOUNT_REASONS[0]);
  const [asking, setAsking] = useState(false);
  const n = Number(value || 0);
  const amount = kind === "amount" ? Math.min(n, bill.gross) : Math.round((bill.gross * n) / 100);
  const go = (approvalId?: string) =>
    discountBill(bill.id, kind, n, reason, approvalId).then(onDone, (e) => (setAsking(false), onError(errorText(e))));
  const apply = () => (session.permissions.discount === "approval" ? setAsking(true) : go());

  if (asking) {
    return (
      <ApprovalDialog
        action="discount"
        what={n ? `Discount ${kind === "percent" ? `${n}%` : formatKsh(n)} (−${formatKsh(amount)}) on ${bill.place}: ${reason}` : `Remove the discount on ${bill.place}`}
        requestedBy={session.staff.name}
        reason={reason}
        onApproved={(id) => go(id)}
        onCancel={() => setAsking(false)}
      />
    );
  }
  return (
    <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
      <div className="choice-list grow">
        <div className="row">
          <button className={`btn grow ${kind === "amount" ? "btn-primary" : "btn-quiet"}`} onClick={() => setKind("amount")}>
            KSh amount
          </button>
          <button className={`btn grow ${kind === "percent" ? "btn-primary" : "btn-quiet"}`} onClick={() => setKind("percent")}>
            Percent %
          </button>
        </div>
        <div className="field-box active">
          <span className="muted">{kind === "percent" ? "Percent off" : "Shillings off"}</span>
          <strong>{value ? (kind === "percent" ? `${value}%` : formatKsh(n)) : "—"}</strong>
        </div>
        <div className="row muted" style={{ fontSize: 20 }}>
          <span className="grow">
            {formatKsh(bill.gross)} − {formatKsh(amount)}
          </span>
          <strong>= {formatKsh(bill.gross - amount)}</strong>
        </div>
        <div className="choice-grid">
          {DISCOUNT_REASONS.map((r) => (
            <button key={r} className={`choice ${reason === r ? "selected" : ""}`} onClick={() => setReason(r)}>
              {r}
            </button>
          ))}
        </div>
        <div className="row row-end">
          {bill.discount > 0 && (
            <button className="btn btn-quiet" onClick={() => (setValue(""), session.permissions.discount === "approval" ? setAsking(true) : discountBill(bill.id, kind, 0, "Removed").then(onDone, (e) => onError(errorText(e))))}>
              Remove discount
            </button>
          )}
          <button className="btn btn-primary" disabled={!n} onClick={apply}>
            APPLY
          </button>
        </div>
      </div>
      <Keypad value={value} onChange={(v) => setValue(v.replace(/^0+/, ""))} onEnter={apply} maxLength={kind === "percent" ? 3 : 7} />
    </div>
  );
}
