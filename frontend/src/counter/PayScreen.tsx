import { ArrowLeft, Banknote, BookUser, CheckCircle2, CreditCard, ReceiptText, Smartphone, TriangleAlert, UserX } from "lucide-react";
import { useEffect, useState } from "react";
import {
  ApiError,
  getBill,
  getSettings,
  markUnpaid,
  reprint,
  takePayment,
  type Bill,
  type PaymentIn,
  type Session,
  type Settings,
} from "../services/api";
import { ApprovalDialog } from "../shared/ApprovalDialog";
import { CodeKeypad } from "../shared/CodeKeypad";
import { Keypad } from "../shared/Keypad";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";
import { ReceiptPreview } from "../shared/Receipt";
import { CreditDialog } from "./CreditDialog";

type Props = {
  session: Session;
  billId: string;
  onBack: () => void;
  onDone: (message: string, warning?: boolean) => void;
};

type Field = "amount" | "given" | "tip" | "code" | "card";
type Done = {
  change: number;
  method: "cash" | "mpesa" | "card" | "credit" | "unpaid";
  receiptPrinted: boolean;
  receiptId?: string;
  place: string;
  note?: string;
};

const CODE_LENGTH = { last4: 4, full: 10, none: 0 } as const;
const num = (s: string) => (s ? parseInt(s, 10) : 0);

/** Take payment (masterplan 4.3). Several payments can share a bill: pay part, and the
 * bill stays open with the rest to pay. The receipt prints twice when it is all paid. */
export function PayScreen({ session, billId, onBack, onDone }: Props) {
  const [bill, setBill] = useState<Bill | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [method, setMethod] = useState<"cash" | "mpesa" | "card">("cash");
  const [cardRef, setCardRef] = useState("");
  const [amount, setAmount] = useState("");
  const [given, setGiven] = useState("");
  const [tip, setTip] = useState("");
  const [code, setCode] = useState("");
  const [field, setField] = useState<Field>("given");
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Done | null>(null);
  const [crediting, setCrediting] = useState(false);
  const [confirmUnpaid, setConfirmUnpaid] = useState(false);

  useEffect(() => {
    getBill(billId).then((b) => (setBill(b), setAmount(String(b.balance))), (e) => setError(e.message));
    getSettings().then(setSettings, (e) => setError(e.message));
  }, [billId]);

  if (!bill || !settings) return <main className="screen screen-loading">{error ?? <span className="spinner" />}</main>;

  const codeLength = CODE_LENGTH[settings.mpesa_code_entry];
  const due = num(amount);
  const change = num(given) - due;
  const values: Record<Exclude<Field, "code" | "card">, [string, (v: string) => void]> = {
    amount: [amount, setAmount],
    given: [given, setGiven],
    tip: [tip, setTip],
  };
  const ready =
    due > 0 &&
    due <= bill.balance &&
    (method === "cash" ? !given || num(given) >= due : method === "card" ? cardRef.length === 4 : code.length === codeLength);

  const switchTo = (m: "cash" | "mpesa" | "card") => {
    setMethod(m);
    setField(m === "cash" ? "given" : m === "card" ? "card" : codeLength ? "code" : "amount");
    setError(null);
    setDuplicate(null);
  };

  const submit = async (extra: Partial<PaymentIn> = {}) => {
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      const body: PaymentIn =
        method === "cash"
          ? { method, amount: due, tendered: given ? num(given) : due }
          : method === "card"
            ? { method, amount: due, card_ref: cardRef }
            : { method, amount: due, tip: num(tip), mpesa_code: codeLength ? code : undefined, ...extra };
      const { bill: updated, change } = await takePayment(bill.id, body);
      setDuplicate(null);
      if (updated.status === "paid") {
        const receipt = updated.tickets.filter((t) => t.kind === "receipt").pop();
        setDone({ change, method, receiptPrinted: receipt?.status !== "not_printed", receiptId: receipt?.id, place: updated.place });
      } else {
        setBill(updated);
        setAmount(String(updated.balance));
        setGiven("");
        setTip("");
        setCode("");
        setCardRef("");
        setError(null);
      }
    } catch (e) {
      if (e instanceof ApiError && e.code === "mpesa_duplicate") setDuplicate(e.message);
      else setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    const warn = done.method === "unpaid" || !done.receiptPrinted;
    const finish = () =>
      onDone(`${done.place}: ${done.method === "credit" ? "on credit" : done.method === "unpaid" ? "marked unpaid" : "paid"} ✓`, !done.receiptPrinted);
    return (
      <main className="paid">
        <section className="paid-left">
          <svg className={`paid-check ${done.method === "unpaid" ? "warn" : ""}`} viewBox="0 0 112 112" aria-hidden>
            <circle cx="56" cy="56" r="52" />
            <path d="M34 58 l15 15 l30 -32" />
          </svg>
          <div className={done.method === "unpaid" ? "paid-badge warn" : "paid-badge"}>
            {done.method === "credit" ? "ON CREDIT" : done.method === "unpaid" ? "UNPAID" : "PAID"}
          </div>
          <div className="muted" style={{ fontSize: 22 }}>
            {done.place}
            {done.note && ` · ${done.note}`}
          </div>
          {done.method === "cash" && (
            <div className="change">
              <span>CHANGE</span>
              <strong>{formatKsh(done.change)}</strong>
            </div>
          )}
          {done.method !== "unpaid" && !done.receiptPrinted && (
            <p className="warn" style={{ fontSize: 19, fontWeight: 650 }}>
              The receipt did NOT print. Print it again from here.
            </p>
          )}
          <button className="btn btn-primary" style={{ minWidth: 280 }} onClick={finish}>
            <CheckCircle2 size={22} /> DONE
          </button>
          {warn && <span className="muted">The screen locks when you're done.</span>}
        </section>
        <section className="paid-right">
          {done.receiptId ? (
            <ReceiptPreview
              id={done.receiptId}
              compact
              free={session.permissions.reprint_receipt === "allow"}
              onReprint={done.receiptPrinted ? undefined : () => reprint(done.receiptId!)}
            />
          ) : (
            <div className="empty-state">
              <ReceiptText size={56} />
              No receipt: the bill stays in {session.staff.name}'s cash to hand over.
            </div>
          )}
        </section>
      </main>
    );
  }

  const [fieldValue, setFieldValue] = values[field === "code" || field === "card" ? "amount" : field];
  const dupApproval = session.permissions.mpesa_duplicate_override;

  return (
    <main className="pay">
      <section className="pay-summary">
        <div className="pay-head">
          <button className="icon-btn" onClick={onBack} aria-label="Back to bill">
            <ArrowLeft size={22} />
          </button>
          <span className="place-badge">{bill.place}</span>
          <h2>Bill #{String(bill.number).padStart(4, "0")}</h2>
        </div>
        <div className="due-card">
          <span>{bill.paid > 0 ? "Left to pay" : "To pay"}</span>
          <strong>{formatKsh(bill.balance)}</strong>
          {bill.paid > 0 && (
            <small>
              of {formatKsh(bill.total)} · paid so far{" "}
              {bill.payments
                .filter((p) => !p.reversed)
                .map((p) => `${p.method === "cash" ? "cash" : p.method === "card" ? `card ${p.card_ref ?? ""}` : `M-Pesa ${p.mpesa_ref ?? ""}`} ${formatKsh(p.amount)}`)
                .join(", ")}
            </small>
          )}
        </div>

        <div className="method-tabs three">
          <button className={`method ${method === "cash" ? "on" : ""}`} onClick={() => switchTo("cash")}>
            <span className="method-icon">
              <Banknote size={24} />
            </span>
            Cash
          </button>
          <button className={`method mpesa ${method === "mpesa" ? "on" : ""}`} onClick={() => switchTo("mpesa")}>
            <span className="method-icon">
              <Smartphone size={24} />
            </span>
            M-Pesa
          </button>
          <button className={`method card ${method === "card" ? "on" : ""}`} onClick={() => switchTo("card")}>
            <span className="method-icon">
              <CreditCard size={24} />
            </span>
            Card
          </button>
        </div>

        <FieldBox label="Amount for this bill" value={amount} active={field === "amount"} onClick={() => setField("amount")} note={due < bill.balance ? "Part payment" : undefined} />
        {method === "cash" ? (
          <>
            <FieldBox label="Cash given" value={given} active={field === "given"} onClick={() => setField("given")} />
            <div className={`change ${given && change < 0 ? "under" : ""}`}>
              <span>{given && change < 0 ? "NOT ENOUGH CASH, SHORT BY" : "CHANGE"}</span>
              <strong>{given ? formatKsh(Math.abs(change)) : "—"}</strong>
            </div>
          </>
        ) : method === "card" ? (
          <button className={`field-box ${field === "card" ? "active" : ""}`} onClick={() => setField("card")}>
            <span className="muted">Card slip reference (last 4)</span>
            <strong className="code-value">{cardRef.padEnd(4, "·")}</strong>
          </button>
        ) : (
          <>
            {codeLength > 0 && (
              <button className={`field-box ${field === "code" ? "active" : ""}`} onClick={() => setField("code")}>
                <span className="muted">M-Pesa code ({codeLength === 4 ? "last 4" : "full"})</span>
                <strong className="code-value">{code.padEnd(codeLength, "·")}</strong>
              </button>
            )}
            <FieldBox label="Tip paid to the till (not a sale)" value={tip} active={field === "tip"} onClick={() => setField("tip")} />
          </>
        )}

        {duplicate && (
          <div className="approval-box">
            <TriangleAlert size={28} color="var(--yellow)" />
            <div className="grow">
              <strong>{duplicate}</strong>
              <div className="row" style={{ marginTop: 10 }}>
                {dupApproval === "allow" ? (
                  <button className="btn btn-yellow" onClick={() => submit({ confirm_duplicate: true })}>
                    I CHECKED IT. CONTINUE
                  </button>
                ) : (
                  <button className="btn btn-yellow" onClick={() => setAsking(true)}>
                    GET APPROVAL
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
        <p className="error-text" role="alert">
          {error ?? ""}
        </p>
        <button className={`btn btn-primary pay-go ${method}`} disabled={!ready || busy} onClick={() => submit()}>
          {method === "cash" ? <Banknote size={26} /> : method === "card" ? <CreditCard size={26} /> : <Smartphone size={26} />}
          {method === "cash" ? "TAKE CASH" : method === "card" ? "RECORD CARD" : "RECORD M-PESA"} {due > 0 ? formatKsh(due) : ""}
        </button>
        <div className="row">
          {session.permissions.approve_credit !== "deny" && (
            <button className="btn btn-yellow grow" onClick={() => setCrediting(true)}>
              <BookUser size={20} /> REQUEST CREDIT
            </button>
          )}
          {session.permissions.mark_unpaid_responsible === "own" && (
            <button className="btn btn-quiet grow" onClick={() => setConfirmUnpaid(true)}>
              <UserX size={20} /> Unpaid – I'm responsible
            </button>
          )}
        </div>
      </section>

      <section className="pay-pad">
        {field === "card" ? (
          <div className="pay-code">
            <p className="muted" style={{ margin: "0 0 8px", fontSize: 18 }}>
              Charge {formatKsh(due)} on the card machine, then enter the last 4 characters of the slip's reference
            </p>
            <CodeKeypad value={cardRef} length={4} onChange={setCardRef} />
          </div>
        ) : field === "code" ? (
          <div className="pay-code">
            <p className="muted" style={{ margin: "0 0 8px", fontSize: 18 }}>
              {codeLength === 4 ? "Last 4 characters" : "Full code"} from the customer's M-Pesa message
            </p>
            <CodeKeypad value={code} length={codeLength} onChange={(v) => (setCode(v), setDuplicate(null))} />
          </div>
        ) : (
          <div className="pay-numbers">
            {method === "cash" && field === "given" && (
              <div className="quick-cash">
                <button className="btn btn-quiet" onClick={() => setGiven(String(due))}>
                  Exact
                </button>
                {[500, 1000, 2000].map((n) => (
                  <button key={n} className="btn btn-quiet" onClick={() => setGiven(String(n))}>
                    {formatKsh(n)}
                  </button>
                ))}
              </div>
            )}
            <Keypad value={fieldValue} onChange={(v) => (setFieldValue(v.replace(/^0+/, "")), setError(null))} onEnter={() => submit()} maxLength={7} disabled={asking} />
          </div>
        )}
      </section>

      {crediting && (
        <CreditDialog
          session={session}
          bill={bill}
          onDone={(b) => {
            const receipt = b.tickets.filter((t) => t.kind === "receipt").pop();
            setDone({ change: 0, method: "credit", receiptPrinted: receipt?.status !== "not_printed", receiptId: receipt?.id, place: b.place, note: `${formatKsh(b.credit_amount)} to ${b.credit_customer?.name}` });
          }}
          onClose={() => setCrediting(false)}
        />
      )}

      {confirmUnpaid && (
        <Modal title="Mark unpaid?" onClose={() => setConfirmUnpaid(false)}>
          <p style={{ fontSize: 20, margin: 0 }}>
            {formatKsh(bill.balance)} will stay in the cash you owe at hand-over. Use this for a walk-out or credit nobody approved.
          </p>
          <div className="row row-end">
            <button
              className="btn btn-orange"
              onClick={() =>
                markUnpaid(bill.id).then(
                  (b) => setDone({ change: 0, method: "unpaid", receiptPrinted: true, place: b.place, note: `${formatKsh(bill.balance)} is your responsibility` }),
                  (e) => (setConfirmUnpaid(false), setError(e instanceof ApiError ? e.message : "Something went wrong.")),
                )
              }
            >
              YES, I'M RESPONSIBLE
            </button>
          </div>
        </Modal>
      )}

      {asking && (
        <ApprovalDialog
          action="mpesa_duplicate_override"
          what={`${duplicate} (code ${code}, ${formatKsh(due)})`}
          requestedBy={session.staff.name}
          reason="Customer's M-Pesa message checked"
          onApproved={(id) => (setAsking(false), submit({ approval_id: id }))}
          onCancel={() => setAsking(false)}
        />
      )}
    </main>
  );
}

function FieldBox({ label, value, active, onClick, note }: { label: string; value: string; active: boolean; onClick: () => void; note?: string }) {
  return (
    <button className={`field-box ${active ? "active" : ""}`} onClick={onClick}>
      <span className="muted">
        {label}
        {note && <span className="warn"> · {note}</span>}
      </span>
      <strong>{value ? formatKsh(num(value)) : "—"}</strong>
    </button>
  );
}
