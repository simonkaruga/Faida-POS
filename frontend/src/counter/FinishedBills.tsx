import { useEffect, useState } from "react";
import {
  ApiError,
  cancelPaidBill,
  getBill,
  getFinishedBills,
  reprint,
  type Bill,
  type FinishedBill,
  type Session,
} from "../services/api";
import { ReceiptText } from "lucide-react";
import { ApprovalDialog } from "../shared/ApprovalDialog";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";
import { ReceiptDialog } from "../shared/Receipt";
import { groupLines } from "./billLines";

const STATUS = { paid: "Paid", credit: "On credit", unpaid_responsible: "Unpaid", cancelled: "Cancelled", open: "Open", merged: "Merged" } as const;
const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");
const time = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "");

/** Bills already closed: a waiter's own this shift, or all of today for an Owner or
 * Supervisor. From here a receipt is reprinted or a paid bill cancelled. */
export function FinishedBills({ session, embedded }: { session: Session; embedded?: boolean }) {
  const [bills, setBills] = useState<FinishedBill[] | null>(null);
  const [open, setOpen] = useState<Bill | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => getFinishedBills().then(setBills, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);

  if (!bills) return <p className="muted">{error ?? "Loading…"}</p>;
  return (
    <div className={embedded ? "" : "screen-scroll"}>
      {!bills.length && <p className="muted">No finished bills yet.</p>}
      <div className="list-table">
        {bills.map((b) => (
          <button key={b.id} className="list-row" onClick={() => getBill(b.id).then(setOpen, (e) => setError(errorText(e)))}>
            <span className="mono">#{String(b.number).padStart(4, "0")}</span>
            <span className="grow">
              {b.place} · {b.waiter.name}
            </span>
            <span className={`status-tag ${b.status}`}>{STATUS[b.status]}</span>
            <span className="amount">{formatKsh(b.total)}</span>
            <span className="muted">{time(b.closed_at)}</span>
          </button>
        ))}
      </div>
      <p className="error-text">{error ?? ""}</p>
      {open && <FinishedBillDialog session={session} bill={open} onChanged={(b) => (setOpen(b), load())} onClose={() => setOpen(null)} />}
    </div>
  );
}

function FinishedBillDialog({ session, bill, onChanged, onClose }: { session: Session; bill: Bill; onChanged: (b: Bill) => void; onClose: () => void }) {
  const [asking, setAsking] = useState<null | "reprint" | "not_prepared" | "already_prepared">(null);
  const [cancelling, setCancelling] = useState(false);
  const [viewing, setViewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const receipt = bill.tickets.filter((t) => t.kind === "receipt").pop();
  const canCancel = (bill.status === "paid" || bill.status === "credit") && session.permissions.cancel_paid_bill !== "deny";

  const doReprint = (approvalId?: string) =>
    reprint(receipt!.id, approvalId).then((b) => (setAsking(null), onChanged(b)), (e) => (setAsking(null), setError(errorText(e))));
  const doCancel = (reason: string, approvalId?: string) =>
    cancelPaidBill(bill.id, reason, approvalId).then((b) => (setAsking(null), setCancelling(false), onChanged(b)), (e) => (setAsking(null), setError(errorText(e))));

  if (asking === "reprint") {
    return (
      <ApprovalDialog action="reprint_receipt" what={`Reprint receipt ${receipt?.number} for ${bill.place}`} requestedBy={session.staff.name} reason="Reprint receipt" onApproved={doReprint} onCancel={() => setAsking(null)} />
    );
  }
  if (asking) {
    return (
      <ApprovalDialog
        action="cancel_paid_bill"
        what={`Cancel bill #${String(bill.number).padStart(4, "0")} (${formatKsh(bill.total)}) and give the money back: ${asking === "not_prepared" ? "not prepared" : "already served"}`}
        requestedBy={session.staff.name}
        reason={asking === "not_prepared" ? "Not prepared" : "Already served"}
        onApproved={(id) => doCancel(asking, id)}
        onCancel={() => setAsking(null)}
      />
    );
  }

  const needs = (action: string) => session.permissions[action] === "approval";

  if (viewing && receipt) {
    return (
      <ReceiptDialog
        id={receipt.id}
        title={`Receipt · ${bill.place}`}
        free={!needs("reprint_receipt")}
        onReprint={async () => {
          if (needs("reprint_receipt") && receipt.printed_at) {
            setViewing(false);
            setAsking("reprint");
          } else await doReprint();
        }}
        onClose={() => setViewing(false)}
      />
    );
  }
  return (
    <Modal title={`${bill.place} · #${String(bill.number).padStart(4, "0")} · ${STATUS[bill.status]}`} onClose={onClose}>
      <div className="list-table">
        {groupLines(bill.lines).map((g) => (
          <div key={g.key} className="row" style={{ fontSize: 18 }}>
            <span className="grow">
              {g.lines.length}× {g.name}
            </span>
            <span>{formatKsh(g.unitPrice * g.lines.length)}</span>
          </div>
        ))}
        {bill.discount > 0 && (
          <div className="row muted">
            <span className="grow">Discount</span>
            <span>−{formatKsh(bill.discount)}</span>
          </div>
        )}
        <div className="row" style={{ fontSize: 22, fontWeight: 800 }}>
          <span className="grow">Total</span>
          <span>{formatKsh(bill.total)}</span>
        </div>
        {bill.payments.map((p) => (
          <div key={p.id} className={`row muted ${p.reversed ? "reversed" : ""}`}>
            <span className="grow">
              {p.method === "cash" ? "Cash" : `M-Pesa ${p.mpesa_ref ?? ""}`} · {p.taken_by}
              {p.reversed ? " · given back" : ""}
            </span>
            <span>{formatKsh(p.amount)}</span>
          </div>
        ))}
        {bill.credit_customer && (
          <div className="row muted">
            <span className="grow">On credit: {bill.credit_customer.name}</span>
            <span>{formatKsh(bill.credit_amount)}</span>
          </div>
        )}
      </div>
      {cancelling ? (
        <>
          <p style={{ margin: 0, fontSize: 18 }}>Cancel this bill and give the money back. What happens to the items?</p>
          <div className="choice-list">
            {(["not_prepared", "already_prepared"] as const).map((r) => (
              <button key={r} className="choice" onClick={() => (needs("cancel_paid_bill") ? setAsking(r) : doCancel(r))}>
                <span>{r === "not_prepared" ? "Not prepared" : "Already served"}</span>
                <small>{r === "not_prepared" ? "back to stock" : "recorded as waste"}</small>
              </button>
            ))}
          </div>
        </>
      ) : (
        <div className="row row-end">
          {receipt && (
            <button className="btn btn-quiet" onClick={() => setViewing(true)}>
              <ReceiptText size={20} /> View receipt
            </button>
          )}
          {canCancel && (
            <button className="btn btn-red" onClick={() => setCancelling(true)}>
              Cancel bill
            </button>
          )}
        </div>
      )}
      <p className="error-text">{error ?? ""}</p>
    </Modal>
  );
}
