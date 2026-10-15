import { useEffect, useState } from "react";
import { ApiError, getCustomers, putOnCredit, type Bill, type CreditCustomer, type Session } from "../services/api";
import { ApprovalDialog } from "../shared/ApprovalDialog";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";

/** Request credit (masterplan 4.5): pick the customer; a waiter then needs an Owner or
 * Supervisor PIN. A supervisor can approve only within the customer's limit. */
export function CreditDialog({
  session,
  bill,
  onDone,
  onClose,
}: {
  session: Session;
  bill: Bill;
  onDone: (bill: Bill) => void;
  onClose: () => void;
}) {
  const [customers, setCustomers] = useState<CreditCustomer[] | null>(null);
  const [chosen, setChosen] = useState<CreditCustomer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const needsApproval = session.permissions.approve_credit === "approval";

  useEffect(() => {
    getCustomers().then(setCustomers, (e) => setError(e.message));
  }, []);

  const submit = (customer: CreditCustomer, approvalId?: string) =>
    putOnCredit(bill.id, customer.id, approvalId).then(onDone, (e) => {
      setChosen(null);
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    });

  if (chosen && needsApproval) {
    const over = chosen.owed + bill.balance > chosen.credit_limit;
    return (
      <ApprovalDialog
        action="approve_credit"
        what={`Credit ${formatKsh(bill.balance)} to ${chosen.name} (owes ${formatKsh(chosen.owed)} of ${formatKsh(chosen.credit_limit)})${over ? ". OVER LIMIT: owner only" : ""}`}
        requestedBy={session.staff.name}
        reason={`Credit for ${chosen.name}`}
        onApproved={(id) => submit(chosen, id)}
        onCancel={() => setChosen(null)}
      />
    );
  }

  return (
    <Modal title={`Credit ${formatKsh(bill.balance)} to…`} onClose={onClose} wide>
      {!customers && <p className="muted">Loading…</p>}
      <div className="choice-list">
        {customers?.map((c) => (
          <button
            key={c.id}
            className="choice"
            onClick={() => (needsApproval ? setChosen(c) : submit(c))}
          >
            <span>
              {c.name}
              {c.phone && <small> · {c.phone}</small>}
            </span>
            <small className={c.available < bill.balance ? "warn" : ""}>
              owes {formatKsh(c.owed)} · {formatKsh(c.available)} left of {formatKsh(c.credit_limit)}
            </small>
          </button>
        ))}
        {customers?.length === 0 && <p className="muted">No credit customers yet. The owner adds them in the owner area.</p>}
      </div>
      <p className="error-text" role="alert">
        {error ?? ""}
      </p>
    </Modal>
  );
}
