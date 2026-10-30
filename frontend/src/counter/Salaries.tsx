import { useEffect, useState } from "react";
import {
  addDeduction,
  addEmployee,
  ApiError,
  getActiveStaff,
  getDaysWorked,
  getEmployees,
  getPayEntries,
  giveAdvance,
  paySalary,
  reversePayEntry,
  setShortageStatus,
  removeEmployee,
  updateEmployee,
  type Employee,
  type PaidHow,
  type PayEntry,
  type PayType,
} from "../services/api";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");
const PER = { monthly: "month", weekly: "week", daily: "day" } as const;
const PAID_HOW = { cash_box: "Cash from the box", cash: "Own cash", mpesa: "M-Pesa", bank: "Bank" } as const;
const KIND = { salary: "Salary earned", advance: "Advance", deduction: "Deduction", shortage: "Cash shortage", payment: "Paid", reversal: "Reversed" } as const;
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const nice = (day: string) => new Date(`${day}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

/** What the account balance means, in words. */
function owes(e: Employee, amount = e.balance) {
  if (amount > 0) return { text: `Bar owes ${e.name.split(" ")[0]} ${formatKsh(amount)}`, tone: "" };
  if (amount < 0) return { text: `${e.name.split(" ")[0]} owes the bar ${formatKsh(-amount)}`, tone: "warn" };
  return { text: "Settled", tone: "muted" };
}

/** Salaries (owner): who is paid how much, advances, deductions and shortages, and what is
 * left to pay. Money paid out is a Salaries expense. */
export function SalariesTab() {
  const [rows, setRows] = useState<Employee[] | null>(null);
  const [dialog, setDialog] = useState<null | { kind: "add" | "edit" | "pay" | "advance" | "deduct" | "history"; e?: Employee }>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => getEmployees().then(setRows, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);
  if (!rows) return <p className="muted">{error ?? "Loading…"}</p>;
  const done = (text?: string) => (setDialog(null), setMessage(text ?? null), load());
  const active = rows.filter((e) => e.active);
  const left = rows.filter((e) => !e.active);
  const toPay = active.reduce((s, e) => s + Math.max(e.balance, 0), 0);

  const row = (e: Employee) => {
    const b = owes(e);
    return (
      <div key={e.id} className="shift-row" style={{ flexWrap: "wrap" }}>
        <span className="grow" style={{ minWidth: 220 }}>
          <strong>{e.name}</strong>
          <span className="muted">
            {e.job ? ` · ${e.job}` : ""}
            {e.staff_name ? ` · PIN: ${e.staff_name}` : ""}
          </span>
          <br />
          <span className="muted">
            {formatKsh(e.pay_rate)} per {PER[e.pay_type]}
            {e.paid_to ? ` · paid up to ${nice(e.paid_to)}` : " · not paid yet"}
          </span>
        </span>
        {e.shortages.length > 0 && (
          <span className="status-tag unpaid_responsible">
            {e.shortages.length} shortage{e.shortages.length > 1 ? "s" : ""} to decide: {formatKsh(e.shortages.reduce((s, x) => s + x.amount, 0))}
          </span>
        )}
        <span className={b.tone} style={{ minWidth: 200, textAlign: "right", fontWeight: 700 }}>
          {b.text}
        </span>
        {e.active && (
          <>
            <button className="btn btn-primary" onClick={() => setDialog({ kind: "pay", e })}>
              PAY
            </button>
            <button className="btn btn-quiet" onClick={() => setDialog({ kind: "advance", e })}>
              Advance
            </button>
            <button className="btn btn-quiet" onClick={() => setDialog({ kind: "deduct", e })}>
              Deduct
            </button>
          </>
        )}
        <button className="btn btn-quiet" onClick={() => setDialog({ kind: "history", e })}>
          History
        </button>
        <button className="btn btn-quiet" onClick={() => setDialog({ kind: "edit", e })}>
          Change / remove
        </button>
      </div>
    );
  };

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <h2 className="section-title grow" style={{ margin: 0 }}>
          {active.length} {active.length === 1 ? "employee" : "employees"} · to pay now {formatKsh(toPay)}
        </h2>
        <button className="btn btn-primary" onClick={() => setDialog({ kind: "add" })}>
          ADD EMPLOYEE
        </button>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        Each person has a pay account. Salary earned goes in; advances, deductions (e.g. broken glasses) and cash shortages you mark{" "}
        <strong>Deducted</strong> come off; what you pay comes off. Link a waiter's PIN to see their shortages here. Deductions are your decision:
        Kenyan law (Employment Act s.19) limits what may be taken from wages.
      </p>
      {message && <p className="ok-text">{message}</p>}
      <div className="list-table">
        {active.map(row)}
        {!active.length && <p className="muted">No employees yet. Add the people you pay, with or without a PIN.</p>}
      </div>
      {left.length > 0 && (
        <>
          <h2 className="section-title">No longer working here</h2>
          <div className="list-table">{left.map(row)}</div>
        </>
      )}
      <p className="error-text">{error ?? ""}</p>
      {dialog?.kind === "add" && <EmployeeDialog onDone={() => done()} onClose={() => setDialog(null)} />}
      {dialog?.kind === "edit" && dialog.e && <EmployeeDialog employee={dialog.e} onDone={() => done()} onClose={() => setDialog(null)} />}
      {dialog?.kind === "pay" && dialog.e && <PayDialog employee={dialog.e} onDone={done} onClose={() => setDialog(null)} />}
      {(dialog?.kind === "advance" || dialog?.kind === "deduct") && dialog.e && (
        <MoneyDialog kind={dialog.kind} employee={dialog.e} onDone={done} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === "history" && dialog.e && <HistoryDialog employee={dialog.e} onChanged={load} onClose={() => setDialog(null)} />}
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="form-field grow" style={{ minWidth: 0, flexBasis: 0 }}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function Input({ value, onChange, placeholder, numeric, type }: { value: string; onChange: (v: string) => void; placeholder?: string; numeric?: boolean; type?: string }) {
  return (
    <input
      className="text-input"
      style={{ width: "100%", minWidth: 0 }}
      type={type}
      placeholder={placeholder}
      inputMode={numeric ? "numeric" : undefined}
      value={value}
      onChange={(e) => onChange(numeric ? e.target.value.replace(/\D/g, "") : e.target.value)}
    />
  );
}

function PaidHowPicker({ value, onChange }: { value: PaidHow; onChange: (v: PaidHow) => void }) {
  return (
    <div className="segmented">
      {(Object.keys(PAID_HOW) as PaidHow[]).map((h) => (
        <button key={h} className={value === h ? "on" : ""} onClick={() => onChange(h)}>
          {PAID_HOW[h]}
        </button>
      ))}
    </div>
  );
}

function EmployeeDialog({ employee, onDone, onClose }: { employee?: Employee; onDone: () => void; onClose: () => void }) {
  const [f, setF] = useState({
    name: employee?.name ?? "",
    job: employee?.job ?? "",
    phone: employee?.phone ?? "",
    rate: employee ? String(employee.pay_rate) : "",
  });
  const [payType, setPayType] = useState<PayType>(employee?.pay_type ?? "monthly");
  const [staffId, setStaffId] = useState<string | null>(employee?.staff_id ?? null);
  const [staff, setStaff] = useState<{ id: string; name: string }[]>([]);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getActiveStaff().then(setStaff, () => {});
  }, []);
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });
  const remove = () => employee && removeEmployee(employee.id).then(onDone, (e) => setError(errorText(e)));
  const body = { name: f.name.trim(), job: f.job.trim() || null, phone: f.phone.trim() || null, staff_id: staffId, pay_type: payType, pay_rate: Number(f.rate || 0) };
  const save = (extra: { active?: boolean } = {}) =>
    (employee ? updateEmployee(employee.id, { ...body, ...extra }) : addEmployee(body)).then(onDone, (e) => setError(errorText(e)));
  return (
    <Modal title={employee ? `Change ${employee.name}` : "New employee"} onClose={onClose} wide>
      <div className="row">
        <Field label="Name">
          <Input value={f.name} onChange={set("name")} placeholder="e.g. Jane Wanjiru" />
        </Field>
        <Field label="Job (optional)">
          <Input value={f.job} onChange={set("job")} placeholder="e.g. Waitress, Cook, Guard" />
        </Field>
        <Field label="Phone (optional)">
          <Input value={f.phone} onChange={set("phone")} placeholder="07…" />
        </Field>
      </div>
      <h3 className="form-title">Paid</h3>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <div className="segmented">
          {(["monthly", "weekly", "daily"] as const).map((t) => (
            <button key={t} className={payType === t ? "on" : ""} onClick={() => setPayType(t)}>
              {{ monthly: "Monthly", weekly: "Weekly", daily: "Per day worked" }[t]}
            </button>
          ))}
        </div>
        <Field label={`Pay per ${PER[payType]} (KSh)`}>
          <Input value={f.rate} onChange={set("rate")} placeholder={payType === "daily" ? "e.g. 800" : "e.g. 15000"} numeric />
        </Field>
      </div>
      <h3 className="form-title">Their PIN (optional: links their cash shortages, and days worked for a daily wage)</h3>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <button className={`btn ${staffId === null ? "btn-primary" : "btn-quiet"}`} onClick={() => setStaffId(null)}>
          No PIN
        </button>
        {staff.map((s) => (
          <button key={s.id} className={`btn ${staffId === s.id ? "btn-primary" : "btn-quiet"}`} onClick={() => setStaffId(s.id)}>
            {s.name}
          </button>
        ))}
      </div>
      <p className="error-text">{error ?? ""}</p>
      {removing && employee ? (
        <div className="row">
          <span className="warn grow">
            Remove {employee.name}? Added by mistake (nothing paid yet): deleted. Otherwise kept under "No longer working here", with their pay
            history.
          </span>
          <button className="btn btn-quiet" onClick={() => setRemoving(false)}>
            Keep
          </button>
          <button className="btn btn-red" onClick={remove}>
            REMOVE
          </button>
        </div>
      ) : (
        <div className="row row-end">
          {employee?.active && (
            <button className="btn btn-quiet" onClick={() => setRemoving(true)}>
              Remove employee
            </button>
          )}
          {employee && !employee.active && (
            <button className="btn btn-quiet" onClick={() => save({ active: true })}>
              Works here again
            </button>
          )}
          <button className="btn btn-primary" disabled={!f.name.trim() || !f.rate} onClick={() => save()}>
            {employee ? "SAVE" : "ADD EMPLOYEE"}
          </button>
        </div>
      )}
    </Modal>
  );
}

function MoneyDialog({ kind, employee, onDone, onClose }: { kind: "advance" | "deduct"; employee: Employee; onDone: (text: string) => void; onClose: () => void }) {
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [ref, setRef] = useState("");
  const [paidHow, setPaidHow] = useState<PaidHow>("cash_box");
  const [error, setError] = useState<string | null>(null);
  const n = Number(amount || 0);
  const save = () =>
    (kind === "advance"
      ? giveAdvance(employee.id, { amount: n, paid_how: paidHow, reference: ref.trim() || undefined, note: note.trim() || undefined })
      : addDeduction(employee.id, { amount: n, note: note.trim() })
    ).then((e) => onDone(`${kind === "advance" ? "Advance" : "Deduction"} of ${formatKsh(n)} recorded. ${owes(e).text}.`), (e) => setError(errorText(e)));
  return (
    <Modal title={kind === "advance" ? `Advance to ${employee.name}` : `Deduct from ${employee.name}'s pay`} onClose={onClose} wide>
      <p className="muted" style={{ margin: 0 }}>
        {kind === "advance"
          ? "Money given before pay day. It comes off their next pay."
          : "Something they must pay back from their pay, e.g. broken glasses. It is your decision: say why."}
      </p>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <Field label="Amount (KSh)">
          <Input value={amount} onChange={setAmount} placeholder="e.g. 2000" numeric />
        </Field>
        <Field label={kind === "advance" ? "Note (optional)" : "Why"}>
          <Input value={note} onChange={setNote} placeholder={kind === "advance" ? "e.g. school fees" : "e.g. broke 3 glasses"} />
        </Field>
      </div>
      {kind === "advance" && (
        <>
          <h3 className="form-title">Paid how</h3>
          <PaidHowPicker value={paidHow} onChange={setPaidHow} />
          {paidHow !== "cash_box" && (
            <Field label="M-Pesa code or reference (optional)">
              <Input value={ref} onChange={setRef} />
            </Field>
          )}
        </>
      )}
      <p className="muted">After this: {owes(employee, employee.balance - n).text}</p>
      <p className="error-text">{error ?? ""}</p>
      <div className="row row-end">
        <button className="btn btn-primary" disabled={!n || (kind === "deduct" && !note.trim())} onClick={save}>
          {kind === "advance" ? `GIVE ${formatKsh(n)}` : `DEDUCT ${formatKsh(n)}`}
        </button>
      </div>
    </Modal>
  );
}

/** The start of the next period to pay: the day after the last one paid, or a guess. */
function defaultStart(e: Employee, today: Date): string {
  if (e.paid_to) {
    const d = new Date(`${e.paid_to}T12:00:00`);
    d.setDate(d.getDate() + 1);
    return iso(d);
  }
  if (e.pay_type === "monthly") return iso(new Date(today.getFullYear(), today.getMonth(), 1));
  if (e.pay_type === "weekly") return iso(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6));
  return iso(today);
}

function PayDialog({ employee, onDone, onClose }: { employee: Employee; onDone: (text: string) => void; onClose: () => void }) {
  const [e, setE] = useState(employee);
  const today = new Date();
  const [start, setStart] = useState(defaultStart(employee, today));
  const [end, setEnd] = useState(iso(today));
  const [days, setDays] = useState("");
  const [earned, setEarned] = useState(employee.pay_type === "daily" ? "" : String(employee.pay_rate));
  const [paid, setPaid] = useState<string | null>(null);
  const [paidHow, setPaidHow] = useState<PaidHow>("cash_box");
  const [ref, setRef] = useState("");
  const [error, setError] = useState<string | null>(null);
  const daily = e.pay_type === "daily";
  useEffect(() => {
    if (!daily || !start || !end) return;
    getDaysWorked(e.id, start, end).then((r) => {
      if (r.days_worked !== null) {
        setDays(String(r.days_worked));
        setEarned(String(r.days_worked * e.pay_rate));
      }
    }, () => {});
  }, [daily, start, end, e.id, e.pay_rate]);
  const reload = () => getEmployees().then((all) => setE(all.find((x) => x.id === e.id) ?? e), () => {});
  const decide = (handoverId: string, outcome: "deducted" | "forgiven") => setShortageStatus(handoverId, outcome).then(reload, (err) => setError(errorText(err)));

  const earnedN = Number(earned || 0);
  const due = e.balance + earnedN;
  const paidN = paid === null ? Math.max(due, 0) : Number(paid || 0);
  const save = () =>
    paySalary(e.id, { period_start: start, period_end: end, earned: earnedN, paid: paidN, paid_how: paidHow, reference: ref.trim() || undefined }).then(
      (after) => onDone(`${e.name}: paid ${formatKsh(paidN)}. ${owes(after).text}.`),
      (err) => setError(errorText(err)),
    );
  return (
    <Modal title={`Pay ${e.name}`} onClose={onClose} wide>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <Field label="Pays for, from">
          <Input type="date" value={start} onChange={setStart} />
        </Field>
        <Field label="to">
          <Input type="date" value={end} onChange={setEnd} />
        </Field>
        {daily && (
          <Field label={`Days worked × ${formatKsh(e.pay_rate)}`}>
            <Input value={days} onChange={(v) => (setDays(v), setEarned(String(Number(v || 0) * e.pay_rate)))} placeholder="e.g. 26" numeric />
          </Field>
        )}
        <Field label="Salary earned (KSh)">
          <Input value={earned} onChange={setEarned} numeric />
        </Field>
      </div>
      {e.shortages.length > 0 && (
        <>
          <h3 className="form-title">Cash shortages not decided yet</h3>
          {e.shortages.map((s) => (
            <div key={s.handover_id} className="row">
              <span className="grow">
                Short {formatKsh(s.amount)} at hand-over on {nice(s.day)}
              </span>
              <button className="btn btn-quiet" onClick={() => decide(s.handover_id, "deducted")}>
                Deduct from pay
              </button>
              <button className="btn btn-quiet" onClick={() => decide(s.handover_id, "forgiven")}>
                Forgive
              </button>
            </div>
          ))}
        </>
      )}
      <div className="cashup" style={{ margin: "12px 0" }}>
        <div className="cashup-row">
          <span>Salary earned</span>
          <span>{formatKsh(earnedN)}</span>
        </div>
        <div className="cashup-row">
          <span>{e.balance < 0 ? "− Advances, deductions and shortages" : "+ Still owed from before"}</span>
          <span>{formatKsh(Math.abs(e.balance))}</span>
        </div>
        <div className="cashup-row grand">
          <span>{due >= 0 ? "= TO PAY" : "= THEY STILL OWE THE BAR"}</span>
          <span>{formatKsh(Math.abs(due))}</span>
        </div>
      </div>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <Field label="Paying now (KSh)">
          <Input value={paid ?? String(Math.max(due, 0))} onChange={setPaid} numeric />
        </Field>
        <Field label="Reference (optional)">
          <Input value={ref} onChange={setRef} placeholder="M-Pesa code" />
        </Field>
      </div>
      <h3 className="form-title">Paid how</h3>
      <PaidHowPicker value={paidHow} onChange={setPaidHow} />
      <p className="muted">After paying: {owes(e, due - paidN).text}</p>
      <p className="error-text">{error ?? ""}</p>
      <div className="row row-end">
        <button className="btn btn-primary" disabled={!start || !end || paidN > Math.max(due, 0)} onClick={save}>
          PAY {formatKsh(paidN)}
        </button>
      </div>
    </Modal>
  );
}

function HistoryDialog({ employee, onChanged, onClose }: { employee: Employee; onChanged: () => void; onClose: () => void }) {
  const [rows, setRows] = useState<PayEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => getPayEntries(employee.id).then(setRows, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, [employee.id]);
  const undo = (id: string) => reversePayEntry(id).then(() => (load(), onChanged()), (e) => setError(errorText(e)));
  return (
    <Modal title={`${employee.name}: pay account`} onClose={onClose} wide>
      <div className="list-table movements">
        {rows?.map((r) => (
          <div key={r.id} className={`row ${r.reversed ? "reversed-row" : ""}`} style={{ fontSize: 17 }}>
            <span className="muted" style={{ minWidth: 80 }}>
              {nice(r.business_day)}
            </span>
            <span style={{ minWidth: 140 }}>{KIND[r.kind]}</span>
            <span className="grow muted">
              {r.note}
              {r.by ? ` · ${r.by}` : ""}
            </span>
            <span className={r.amount < 0 ? "warn" : ""} style={{ minWidth: 100, textAlign: "right" }}>
              {r.amount < 0 ? "−" : "+"}
              {formatKsh(Math.abs(r.amount))}
            </span>
            <span style={{ minWidth: 140, textAlign: "right" }}>
              <span className="muted">balance </span>
              <strong>{r.balance < 0 ? "−" : ""}{formatKsh(Math.abs(r.balance))}</strong>
            </span>
            {!r.reversed && r.kind !== "reversal" && r.kind !== "shortage" ? (
              <button className="btn btn-quiet" onClick={() => undo(r.id)}>
                Reverse
              </button>
            ) : (
              <span style={{ minWidth: 96 }} />
            )}
          </div>
        ))}
        {rows?.length === 0 && <p className="muted">Nothing yet.</p>}
      </div>
      <p className="muted">Balance above 0: the bar owes them. Below 0: they owe the bar. A shortage is changed in Shifts &amp; hand-overs.</p>
      <p className="error-text">{error ?? ""}</p>
    </Modal>
  );
}
