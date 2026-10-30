import { useEffect, useState } from "react";
import {
  ApiError,
  checkReceiver,
  closeShift,
  getMyShift,
  markUnpaid,
  type CashUp,
  type Handover,
  type MyShift,
  type Person,
  type Session,
} from "../services/api";
import { Keypad } from "../shared/Keypad";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";
import { CashUpTable } from "./CashUpTable";

type Props = {
  session: Session;
  onPay: (billId: string) => void;
  onBack: () => void;
  onDone: (message: string, warning?: boolean) => void;
};

const NOTES = ["1000", "500", "200", "100", "50"] as const;
type CountKey = (typeof NOTES)[number] | "coins";
const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");

/** End my shift (masterplan 4.6): 1 open bills, 2 summary, 3 receive cash, 4 sign-off. */
export function EndShift({ session, onPay, onBack, onDone }: Props) {
  const [mine, setMine] = useState<MyShift | null>(null);
  const [step, setStep] = useState<"bills" | "declare" | "summary" | "receiver" | "count" | "sign" | "done">("bills");
  // What the waiter says they sold, typed before Faida's figures are shown.
  const [said, setSaid] = useState({ cash: "", mpesa: "", credit: "" });
  const [error, setError] = useState<string | null>(null);
  const [unpaidFor, setUnpaidFor] = useState<{ id: string; place: string; balance: number } | null>(null);
  const [receiverPin, setReceiverPin] = useState("");
  const [receiver, setReceiver] = useState<{ person: Person; cash: CashUp } | null>(null);
  const [byNote, setByNote] = useState(true);
  const [counts, setCounts] = useState<Record<CountKey, string>>({ "1000": "", "500": "", "200": "", "100": "", "50": "", coins: "" });
  const [selected, setSelected] = useState<CountKey>("1000");
  const [typedTotal, setTypedTotal] = useState("");
  const [receiverNote, setReceiverNote] = useState("");
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [staffPin, setStaffPin] = useState("");
  const [disagree, setDisagree] = useState(false);
  const [staffNote, setStaffNote] = useState("");
  const [result, setResult] = useState<Handover | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    getMyShift().then((m) => {
      setMine(m);
      setStep(m.open_bills.length ? "bills" : "declare");
    }, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);

  if (!mine) return <main className="screen-center">{error ?? "Loading…"}</main>;
  if (!mine.shift || !mine.cash_up) {
    return (
      <main className="screen-center">
        <p>You have no open shift. It starts with your first bill or float.</p>
        <button className="btn btn-primary" onClick={onBack}>
          BACK
        </button>
      </main>
    );
  }

  const cash = receiver?.cash ?? mine.cash_up;
  const expected = cash.cash_to_hand_over;
  const counted = byNote
    ? NOTES.reduce((sum, n) => sum + Number(n) * Number(counts[n] || 0), 0) + Number(counts.coins || 0)
    : Number(typedTotal || 0);
  const difference = counted - expected;
  const resultText = difference === 0 ? "BALANCED" : difference < 0 ? `SHORT ${formatKsh(-difference)}` : `OVER ${formatKsh(difference)}`;
  const resultClass = difference === 0 ? "balanced" : difference < 0 ? "short" : "over";
  const shiftId = mine.shift.id;
  const name = session.staff.name;

  const verifyReceiver = async () => {
    setBusy(true);
    try {
      const r = await checkReceiver(shiftId, receiverPin);
      setReceiver({ person: r.receiver, cash: r.cash_up });
      setStep("count");
      setError(null);
    } catch (e) {
      setError(errorText(e));
      setReceiverPin("");
    } finally {
      setBusy(false);
    }
  };

  const signOff = async () => {
    if (disagree && !staffNote.trim()) return setError("Say why you disagree.");
    setBusy(true);
    try {
      const notes = Object.fromEntries(Object.entries(counts).map(([k, v]) => [k, Number(v || 0)]));
      const handover = await closeShift(shiftId, {
        receiver_pin: receiverPin,
        ...(byNote ? { counted_notes: notes } : { received: counted }),
        receiver_note: receiverNote.trim() || undefined,
        staff_pin: staffPin,
        agree: !disagree,
        staff_note: staffNote.trim() || undefined,
        declared: { cash: Number(said.cash || 0), mpesa: Number(said.mpesa || 0), credit: Number(said.credit || 0) },
      });
      setResult(handover);
      setStep("done");
      setError(null);
    } catch (e) {
      setError(errorText(e));
      setStaffPin("");
    } finally {
      setBusy(false);
    }
  };

  const header = (title: string, n: number) => (
    <header className="shift-head">
      <span className="step-badge">{n} / 5</span>
      <h2>{title}</h2>
    </header>
  );

  switch (step) {
    case "bills":
      return (
        <main className="screen">
          <div className="screen-scroll">
            {header("End my shift: finish your open bills", 1)}
            <p className="muted" style={{ fontSize: 18 }}>
              You can't end your shift while you have open bills. For each one: take payment, ask for credit, or mark it
              unpaid if you take responsibility for it.
            </p>
            <div className="choice-list">
              {mine.open_bills.map((b) => (
                <div key={b.id} className="open-bill-row">
                  <span className="grow">
                    <strong>{b.place}</strong> · #{String(b.number).padStart(4, "0")} · {formatKsh(b.balance)} to pay
                  </span>
                  <button className="btn btn-primary" onClick={() => onPay(b.id)}>
                    PAY / CREDIT
                  </button>
                  {session.permissions.mark_unpaid_responsible === "own" && (
                    <button className="btn btn-orange" onClick={() => setUnpaidFor(b)}>
                      Unpaid – I'm responsible
                    </button>
                  )}
                </div>
              ))}
            </div>
            <p className="error-text">{error ?? ""}</p>
          </div>
          <footer className="screen-actions">
            <button className="btn btn-quiet" onClick={onBack}>
              ‹ Back
            </button>
          </footer>
          {unpaidFor && (
            <Modal title="Mark unpaid?" onClose={() => setUnpaidFor(null)}>
              <p style={{ fontSize: 20, margin: 0 }}>
                {unpaidFor.place}: <strong>{formatKsh(unpaidFor.balance)}</strong> will stay in the cash you owe at hand-over.
              </p>
              <div className="row row-end">
                <button
                  className="btn btn-orange"
                  onClick={() =>
                    markUnpaid(unpaidFor.id).then(
                      () => (setUnpaidFor(null), load()),
                      (e) => (setUnpaidFor(null), setError(errorText(e))),
                    )
                  }
                >
                  YES, I'M RESPONSIBLE
                </button>
              </div>
            </Modal>
          )}
        </main>
      );

    case "declare": {
      const box = (k: keyof typeof said, label: string) => (
        <label className="form-field" style={{ fontSize: 20 }}>
          <span>{label}</span>
          <input
            className="text-input"
            style={{ fontSize: 26 }}
            inputMode="numeric"
            placeholder="KSh"
            value={said[k]}
            onChange={(e) => setSaid({ ...said, [k]: e.target.value.replace(/\D/g, "") })}
          />
        </label>
      );
      return (
        <main className="screen">
          <div className="screen-scroll shift-body">
            {header(`${name}: what did you sell?`, 2)}
            <p className="muted" style={{ fontSize: 18 }}>
              Before you see Faida's figures, type what you think you sold this shift. Type 0 if none.
            </p>
            <div className="row" style={{ alignItems: "flex-end", maxWidth: 820 }}>
              {box("cash", "Cash")}
              {box("mpesa", "M-Pesa")}
              {box("credit", "Credit")}
            </div>
          </div>
          <footer className="screen-actions">
            <button className="btn btn-quiet" onClick={onBack}>
              ‹ Back
            </button>
            <span className="grow" />
            <button className="btn btn-primary" disabled={!said.cash || !said.mpesa || !said.credit} onClick={() => (setStep("summary"), setError(null))}>
              NEXT: SEE MY SUMMARY
            </button>
          </footer>
        </main>
      );
    }

    case "summary":
      return (
        <main className="screen">
          <div className="screen-scroll shift-body">
            {header(`${name}: my shift summary`, 3)}
            <CashUpTable cash={cash} />
            <h3 className="form-title">What you said you sold, and Faida's figures</h3>
            <div className="cashup">
              {(
                [
                  ["Cash", Number(said.cash || 0), cash.cash_due_from_sales - cash.unpaid_responsible],
                  ["M-Pesa", Number(said.mpesa || 0), cash.mpesa],
                  ["Credit", Number(said.credit || 0), cash.credit],
                ] as const
              ).map(([label, you, faida]) => (
                <div key={label} className="cashup-row">
                  <span>{label}</span>
                  <span>
                    you {formatKsh(you)} · Faida {formatKsh(faida)}{" "}
                    <strong className={you === faida ? "ok-text" : "warn"}>
                      {you === faida ? "✓" : `${you > faida ? "+" : "−"}${formatKsh(Math.abs(you - faida))}`}
                    </strong>
                  </span>
                </div>
              ))}
            </div>
          </div>
          <footer className="screen-actions">
            <button className="btn btn-quiet" onClick={onBack}>
              ‹ Back
            </button>
            <span className="grow" />
            <button className="btn btn-primary" onClick={() => (setStep("receiver"), setError(null))}>
              HAND OVER CASH
            </button>
          </footer>
        </main>
      );

    case "receiver":
      return (
        <main className="screen-center">
          {header("Receive cash", 4)}
          <p style={{ fontSize: 20, margin: 0 }}>
            Owner or Supervisor: enter your PIN to receive {name}'s cash
          </p>
          <div style={{ fontSize: 28, letterSpacing: 8, minHeight: 34 }}>{"•".repeat(receiverPin.length)}</div>
          <Keypad value={receiverPin} onChange={(v) => (setReceiverPin(v), setError(null))} onEnter={verifyReceiver} disabled={busy} />
          <p className="error-text">{error ?? ""}</p>
          <button className="btn btn-quiet" onClick={() => setStep("summary")}>
            ‹ Back
          </button>
        </main>
      );

    case "count":
      return (
        <main className="count">
          <section className="count-left">
            {header(`Count ${name}'s cash`, 4)}
            <div className="row">
              <button className={`btn ${byNote ? "btn-primary" : "btn-quiet"}`} onClick={() => setByNote(true)}>
                By note
              </button>
              <button className={`btn ${!byNote ? "btn-primary" : "btn-quiet"}`} onClick={() => setByNote(false)}>
                Type total
              </button>
            </div>
            {byNote ? (
              <div className="note-rows">
                {[...NOTES, "coins" as const].map((n) => (
                  <button key={n} className={`note-row ${selected === n ? "active" : ""}`} onClick={() => setSelected(n)}>
                    <span>{n === "coins" ? "Coins (amount)" : `${formatKsh(Number(n))} ×`}</span>
                    <strong>{counts[n] || "0"}</strong>
                    <span className="muted">
                      {formatKsh(n === "coins" ? Number(counts.coins || 0) : Number(n) * Number(counts[n] || 0))}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="field-box active">
                <span className="muted">Cash received</span>
                <strong>{typedTotal ? formatKsh(Number(typedTotal)) : "—"}</strong>
              </div>
            )}
            <div className="count-result">
              <div>
                Expected <strong>{formatKsh(expected)}</strong>
              </div>
              <div>
                Counted <strong>{formatKsh(counted)}</strong>
              </div>
              <div className={`result-badge ${resultClass}`}>{resultText}</div>
            </div>
            <input className="text-input" placeholder="Note (optional)" value={receiverNote} maxLength={200} onChange={(e) => setReceiverNote(e.target.value)} />
            {cash.mpesa_payments.length > 0 && (
              <details className="mpesa-check">
                <summary>Check {cash.mpesa_payments.length} M-Pesa and card payments against the till and card machine</summary>
                {cash.mpesa_payments.map((m, i) => (
                  <button key={i} className={`mpesa-row ${ticked.has(i) ? "ticked" : ""}`} onClick={() => setTicked(new Set(ticked.has(i) ? [...ticked].filter((x) => x !== i) : [...ticked, i]))}>
                    <span>{ticked.has(i) ? "☑" : "☐"}</span>
                    <span>#{String(m.bill_number).padStart(4, "0")}</span>
                    <span className="pill">{m.method === "card" ? "Card" : "M-Pesa"}</span>
                    <span className="code-value">{m.ref ?? "—"}</span>
                    <span className="grow" />
                    <span>
                      {formatKsh(m.amount)}
                      {m.tip ? ` + ${formatKsh(m.tip)} tip` : ""}
                    </span>
                  </button>
                ))}
              </details>
            )}
            <div className="row">
              <button className="btn btn-quiet" onClick={() => setStep("summary")}>
                ‹ Back
              </button>
              <span className="grow" />
              <button className="btn btn-primary" onClick={() => (setStep("sign"), setError(null))}>
                NEXT: {name.toUpperCase()} SIGNS
              </button>
            </div>
          </section>
          <section className="pay-pad">
            <Keypad
              value={byNote ? counts[selected] : typedTotal}
              onChange={(v) => {
                const clean = v.replace(/^0+/, "");
                if (byNote) setCounts({ ...counts, [selected]: clean });
                else setTypedTotal(clean);
              }}
              onEnter={() => {
                const order: CountKey[] = [...NOTES, "coins"];
                setSelected(order[Math.min(order.indexOf(selected) + 1, order.length - 1)]);
              }}
              maxLength={byNote && selected !== "coins" ? 4 : 7}
              enterLabel="NEXT"
              allowEmptyEnter
            />
          </section>
        </main>
      );

    case "sign":
      return (
        <main className="count">
          <section className="count-left">
            {header(`${name}: sign off`, 5)}
            <div className="count-result">
              <div>
                Expected <strong>{formatKsh(expected)}</strong>
              </div>
              <div>
                Received by {receiver?.person.name} <strong>{formatKsh(counted)}</strong>
              </div>
              <div className={`result-badge ${resultClass}`}>{resultText}</div>
            </div>
            <div className="row">
              <button className={`btn ${!disagree ? "btn-green" : "btn-quiet"}`} onClick={() => setDisagree(false)}>
                I AGREE
              </button>
              <button className={`btn ${disagree ? "btn-red" : "btn-quiet"}`} onClick={() => setDisagree(true)}>
                I disagree
              </button>
            </div>
            {disagree && (
              <input className="text-input" placeholder="Why do you disagree?" value={staffNote} maxLength={200} onChange={(e) => setStaffNote(e.target.value)} />
            )}
            <p style={{ fontSize: 18, margin: 0 }}>{name}: enter your PIN to confirm. Two slips will print.</p>
            <p className="error-text">{error ?? ""}</p>
            <button className="btn btn-quiet" style={{ alignSelf: "flex-start" }} onClick={() => setStep("count")}>
              ‹ Back
            </button>
          </section>
          <section className="pay-pad">
            <div style={{ fontSize: 28, letterSpacing: 8, minHeight: 34 }}>{"•".repeat(staffPin.length)}</div>
            <Keypad value={staffPin} onChange={(v) => (setStaffPin(v), setError(null))} onEnter={signOff} enterLabel="CONFIRM" disabled={busy} />
          </section>
        </main>
      );

    case "done":
      return (
        <main className="screen-center">
          <div className={`result-badge big ${resultClass}`}>{resultText}</div>
          <p style={{ fontSize: 22 }}>
            {name}'s shift is closed. {result?.printed ? "Two slips printed." : "The slips did NOT print: reprint them from the owner area."}
          </p>
          <button className="btn btn-primary" style={{ minWidth: 260 }} onClick={() => onDone(`${name}: shift closed (${resultText.toLowerCase()})`, !result?.printed)}>
            DONE
          </button>
        </main>
      );
  }
}
