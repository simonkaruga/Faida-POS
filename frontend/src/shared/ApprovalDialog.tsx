import { useState } from "react";
import { ApiError, requestApproval } from "../services/api";
import { Keypad } from "./Keypad";
import { Modal } from "./Modal";

type Props = {
  action: string;
  what: string; // e.g. "Remove 1 x Tusker (not prepared)"
  requestedBy: string;
  reason: string;
  onApproved: (approvalId: string) => void;
  onCancel: () => void;
};

/** The approval pop-up (masterplan 4.4): an Owner or Supervisor types their PIN on the
 * waiter's screen to approve or reject. Both outcomes are logged with the reason. */
export function ApprovalDialog({ action, what, requestedBy, reason, onApproved, onCancel }: Props) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const decide = async (decision: "approved" | "rejected") => {
    if (!pin || busy) return;
    setBusy(true);
    try {
      const result = await requestApproval(action, pin, reason, decision);
      if (decision === "approved") onApproved(result.id);
      else onCancel();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setPin("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Approval needed" onClose={onCancel}>
      <div className="approval-box">
        <div>
          <strong>{what}</strong>
        </div>
        <div className="muted">Asked by {requestedBy}</div>
      </div>
      <p className="muted" style={{ margin: 0, fontSize: 18 }}>
        Owner or Supervisor: enter your PIN
      </p>
      <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
        <Keypad value={pin} onChange={(v) => (setPin(v), setError(null))} onEnter={() => decide("approved")} enterLabel="OK" disabled={busy} />
        <div className="choice-list" style={{ minWidth: 170 }}>
          <div style={{ fontSize: 28, letterSpacing: 8 }}>{"•".repeat(pin.length) || " "}</div>
          <button className="btn btn-primary btn-green" onClick={() => decide("approved")} disabled={!pin || busy}>
            APPROVE
          </button>
          <button className="btn btn-red" onClick={() => decide("rejected")} disabled={!pin || busy}>
            Reject
          </button>
        </div>
      </div>
      <p className="error-text" role="alert">
        {error ?? ""}
      </p>
    </Modal>
  );
}
