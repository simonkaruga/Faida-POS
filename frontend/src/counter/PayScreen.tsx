import { useEffect, useState } from "react";
import { ApiError, getBill, getSettings, takePayment, type Bill, type PaymentIn, type Session, type Settings } from "../services/api";
import { ApprovalDialog } from "../shared/ApprovalDialog";
import { CodeKeypad } from "../shared/CodeKeypad";
import { Keypad } from "../shared/Keypad";
import { formatKsh } from "../shared/money";

type Props = {
  session: Session;
  billId: string;
  onBack: () => void;
  onDone: (message: string, warning?: boolean) => void;
};

type Field = "amount" | "given" | "tip" | "code";
type Done = { change: number; method: "cash" | "mpesa"; receiptPrinted: boolean; place: string };

const CODE_LENGTH = { last4: 4, full: 10, none: 0 } as const;
const num = (s: string) => (s ? parseInt(s, 10) : 0);

/** Take payment (masterplan 4.3). Several payments can share a bill: pay part, and the
 * bill stays open with the rest to pay. The receipt prints twice when it is all paid. */
export function PayScreen({ session, billId, onBack, onDone }: Props) {
  const [bill, setBill] = useState<Bill | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [method, setMethod] = useState<"cash" | "mpesa">("cash");
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

  useEffect(() => {
    getBill(billId).then((b) => (setBill(b), setAmount(String(b.balance))), (e) => setError(e.message));
    getSettings().then(setSettings, (e) => setError(e.message));
  }, [billId]);

  if (!bill || !settings) return <main className="screen-center">{error ?? "Loading…"}</main>;

  const codeLength = CODE_LENGTH[settings.mpesa_code_entry];
  const due = num(amount);
  const change = num(given) - due;
  const values: Record<Exclude<Field, "code">, [string, (v: string) => void]> = {
    amount: [amount, setAmount],
    given: [given, setGiven],
    tip: [tip, setTip],
  };
  const ready =
    due > 0 && due <= bill.balance && (method === "cash" ? !given || num(given) >= due : code.length === codeLength);

  const switchTo = (m: "cash" | "mpesa") => {
    setMethod(m);
    setField(m === "cash" ? "given" : codeLength ? "code" : "amount");
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
          : { method, amount: due, tip: num(tip), mpesa_code: codeLength ? code : undefined, ...extra };
      const { bill: updated, change } = await takePayment(bill.id, body);
      setDuplicate(null);
      if (updated.status === "paid") {
        const receipt = updated.tickets.filter((t) => t.kind === "receipt").pop();
        setDone({ change, method, receiptPrinted: receipt?.status !== "not_printed", place: updated.place });
      } else {
        setBill(updated);
        setAmount(String(updated.balance));
        setGiven("");
        setTip("");
        setCode("");
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
    return (
      <main className="screen-center paid">
        <div className="paid-badge">PAID</div>
        <div className="muted" style={{ fontSize: 22 }}>
          {done.place}
        </div>
        {done.method === "cash" && (
          <div className="change">
            <span>CHANGE</span>
            <strong>{formatKsh(done.change)}</strong>
          </div>
        )}
        <p className={done.receiptPrinted ? "muted" : "error-text"} style={{ fontSize: 20 }}>
          {done.receiptPrinted ? "Receipt printed: customer copy and counter copy." : "Receipt NOT printed. Reprint it from the bill."}
        </p>
        <button
          className="btn btn-primary"
          style={{ minWidth: 260 }}
          onClick={() => onDone(`${done.place}: paid ✓`, !done.receiptPrinted)}
        >
          DONE
        </button>
      </main>
    );
  }

  const [fieldValue, setFieldValue] = values[field === "code" ? "amount" : field];
  const dupApproval = session.permissions.mpesa_duplicate_override;

  return (
    <main className="pay">
      <section className="pay-summary">
        <button className="btn btn-quiet" onClick={onBack}>
          ‹ Back to bill
        </button>
        <h2>
          {bill.place} · #{String(bill.number).padStart(4, "0")}
        </h2>
        <div className="pay-figure">
          <span>Total</span>
          <strong>{formatKsh(bill.total)}</strong>
        </div>
        {bill.paid > 0 && (
          <>
            {bill.payments.map((p) => (
              <div key={p.id} className="row muted" style={{ fontSize: 18 }}>
                <span className="grow">
                  {p.method === "cash" ? "Cash" : `M-Pesa ${p.mpesa_ref ?? ""}`}
                  {p.tip ? ` (+${formatKsh(p.tip)} tip)` : ""}
                </span>
                <span>{formatKsh(p.amount)}</span>
              </div>
            ))}
            <div className="pay-figure big">
              <span>Left to pay</span>
              <strong>{formatKsh(bill.balance)}</strong>
            </div>
          </>
        )}

        <div className="method-tabs">
          <button className={`btn ${method === "cash" ? "btn-primary" : "btn-quiet"}`} onClick={() => switchTo("cash")}>
            CASH
          </button>
          <button className={`btn ${method === "mpesa" ? "btn-primary" : "btn-quiet"}`} onClick={() => switchTo("mpesa")}>
            M-PESA
          </button>
        </div>

        <FieldBox label="Amount for this bill" value={amount} active={field === "amount"} onClick={() => setField("amount")} note={due < bill.balance ? "Part payment" : undefined} />
        {method === "cash" ? (
          <>
            <FieldBox label="Cash given" value={given} active={field === "given"} onClick={() => setField("given")} />
            <div className="change">
              <span>CHANGE</span>
              <strong className={given && change < 0 ? "warn" : ""}>{given ? formatKsh(Math.max(change, 0)) : "—"}</strong>
            </div>
          </>
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
            <div>
              <strong>{duplicate}</strong>
            </div>
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
        )}
        <p className="error-text" role="alert">
          {error ?? ""}
        </p>
        <button className="btn btn-primary pay-go" disabled={!ready || busy} onClick={() => submit()}>
          {method === "cash" ? "TAKE CASH" : "RECORD M-PESA"} {due > 0 ? formatKsh(due) : ""}
        </button>
      </section>

      <section className="pay-pad">
        {field === "code" ? (
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
