import { useEffect, useState } from "react";
import { ApiError, getAudit, type AuditEntry } from "../services/api";

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");

/** Plain words for each kind of entry. Anything not listed shows its code, so nothing is hidden. */
const LABEL: Record<string, string> = {
  "approval.approved": "Approved",
  "approval.rejected": "Refused",
  "bill.cancelled": "Paid order cancelled",
  "bill.closed_empty": "Empty order closed",
  "bill.credit": "Put on credit",
  "bill.discounted": "Discount",
  "bill.handed_over": "Order handed over",
  "bill.merged": "Orders merged",
  "bill.moved": "Order moved",
  "bill.split": "Order split",
  "bill.unpaid_responsible": "Unpaid: waiter responsible",
  "bill_line.comped": "Given free",
  "bill_line.voided": "Item removed",
  "business.created": "Business set up",
  "cash.float": "Float given",
  "cash.payout": "Pay-out",
  "cash.owner": "Owner cash",
  "credit.collected": "Credit paid",
  "credit.customer_created": "Credit customer added",
  "credit.customer_updated": "Credit customer changed",
  "day.closed": "Day closed",
  "expense.added": "Expense",
  "expense.reversed": "Expense reversed",
  "menu.back_in": "Back in stock",
  "menu.sold_out": "Sold out",
  "menu.price_changed": "Price changed",
  "menu.loaded": "Menu loaded",
  "menu.category_created": "Category added",
  "menu.category_updated": "Category changed",
  "menu.item_created": "Menu item added",
  "menu.item_updated": "Menu item changed",
  "menu.option_created": "Size added",
  "menu.option_updated": "Size changed",
  "menu.image_set": "Picture added",
  "menu.image_removed": "Picture removed",
  "menu.combo_set": "Combo set",
  "menu.item_modifiers_set": "Choices set",
  "menu.modifier_group_created": "Choice group added",
  "menu.modifier_group_updated": "Choice group changed",
  "menu.modifier_option_created": "Choice added",
  "menu.modifier_option_updated": "Choice changed",
  "menu.price_rule_created": "Happy hour added",
  "menu.price_rule_updated": "Happy hour changed",
  "stock.item_created": "Stock item added",
  "stock.item_updated": "Stock item changed",
  "stock.loaded": "Stock loaded",
  "stock.recipe_set": "Recipe set",
  "table.created": "Table added",
  "table.updated": "Table changed",
  "payment.mpesa_duplicate_accepted": "Repeated M-Pesa code accepted",
  "settings.updated": "Settings changed",
  "shift.closed": "Shift closed",
  "shift.float_given": "Float given",
  "shift.force_closed": "Shift force-closed",
  "shortage.status": "Shortage marked",
  "staff.created": "Staff added",
  "staff.deactivated": "Staff removed",
  "staff.login": "Logged in",
  "staff.pin_reset": "PIN reset",
  "staff.updated": "Staff changed",
  "stock.delivery": "Delivery",
  "stock.take": "Stock take",
  "stock.waste": "Waste",
  "ticket.reprinted": "Reprint",
};

/** Entries the owner should notice: money or stock lost, or rules bent. */
const WATCH = new Set([
  "bill.cancelled", "bill.discounted", "bill.unpaid_responsible", "bill_line.comped", "bill_line.voided",
  "payment.mpesa_duplicate_accepted", "shift.force_closed", "stock.waste", "approval.rejected",
]);

const label = (action: string) => LABEL[action] ?? action.replace(/[._]/g, " ");

/** Changes are stored as [before, after]; empty values (null, or "None" from the server) show as "—". */
function show(value: unknown): string {
  const plain = (v: unknown) => (v === null || v === "None" ? "—" : String(v));
  if (Array.isArray(value) && value.length === 2 && value.every((v) => v === null || typeof v !== "object")) {
    return `${plain(value[0])} → ${plain(value[1])}`;
  }
  if (value !== null && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** The details in one line, e.g. "bill #0142 · item Tusker · reason not_prepared". Ids and
 * stored picture names mean nothing to the owner and are left out. */
function summary(details: Record<string, unknown>): string {
  return Object.entries(details)
    .filter(([k, v]) => k !== "image" && v !== null && v !== "" && !(typeof v === "string" && /^[0-9a-f-]{36}$/.test(v)))
    .map(([k, v]) => (k === "bill" || k === "into" || k === "from" || k === "new") && typeof v === "number"
      ? `${k} #${String(v).padStart(4, "0")}`
      : `${k.replace(/_/g, " ")} ${show(v)}`)
    .join(" · ");
}

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

/** The permanent audit log (masterplan 4.4), newest first. Owner only. Nothing here can be
 * edited or deleted; corrections show as new entries. */
export function AuditLog() {
  const [rows, setRows] = useState<AuditEntry[] | null>(null);
  const [logins, setLogins] = useState(false);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setRows(null);
    getAudit({ logins }).then((r) => (setRows(r), setMore(r.length === 100)), (e) => setError(errorText(e)));
  }, [logins]);
  const older = () => {
    if (!rows?.length) return;
    getAudit({ logins, before: rows[rows.length - 1].created_at })
      .then((r) => (setRows([...rows, ...r]), setMore(r.length === 100)), (e) => setError(errorText(e)));
  };
  return (
    <>
      <div className="row no-print" style={{ marginBottom: 12 }}>
        <p className="muted grow" style={{ margin: 0 }}>
          Everything recorded, newest first. Orange lines are removals, free items, discounts and other losses.
        </p>
        <div className="segmented">
          <button className={!logins ? "on" : ""} onClick={() => setLogins(false)}>Actions</button>
          <button className={logins ? "on" : ""} onClick={() => setLogins(true)}>With logins</button>
        </div>
      </div>
      {!rows ? (
        <div className="screen-loading">{error ?? <span className="spinner" />}</div>
      ) : (
        <div className="list-table">
          {rows.map((e) => (
            <div key={e.id} className="shift-row audit-row">
              <span className="muted" style={{ minWidth: 110 }}>{when(e.created_at)}</span>
              <strong className={WATCH.has(e.action) ? "warn" : ""} style={{ minWidth: 190 }}>{label(e.action)}</strong>
              <span style={{ minWidth: 110 }}>{e.by ?? "—"}</span>
              <span className="grow muted">
                {summary(e.details)}
                {e.approved_by && <> · approved by <strong>{e.approved_by}</strong>{e.reason ? ` (“${e.reason}”)` : ""}</>}
              </span>
            </div>
          ))}
          {!rows.length && <p className="muted">Nothing recorded yet.</p>}
          {more && (
            <button className="btn btn-quiet no-print" onClick={older}>
              OLDER ENTRIES
            </button>
          )}
          <p className="error-text">{error ?? ""}</p>
        </div>
      )}
    </>
  );
}
