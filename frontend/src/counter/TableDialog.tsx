import { Armchair } from "lucide-react";
import { useState } from "react";
import { ApiError, moveBill, type Bill } from "../services/api";
import { CodeKeypad } from "../shared/CodeKeypad";
import { Modal } from "../shared/Modal";

/** Type the table: any number or label ("57", "S12" for a stall table). A table set up in
 * Tables & sections is matched ("7" finds T7); anything else is used as typed. */
export function TableDialog({ bill, onDone, onClose }: { bill: Bill; onDone: (bill: Bill) => void; onClose: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hasTable = Boolean(bill.table_id || bill.table_label);
  const save = () => {
    setBusy(true);
    moveBill(bill.id, { table: value }).then(onDone, (e) => (setError(e instanceof ApiError ? e.message : "Something went wrong."), setBusy(false)));
  };
  return (
    <Modal title={hasTable ? `Order #${String(bill.number).padStart(4, "0")}: change table` : `Which table? (order #${String(bill.number).padStart(4, "0")})`} onClose={onClose} wide>
      <p className="muted" style={{ margin: 0 }}>
        Type the table number, e.g. 57, or S12 for a table brought from the stall. Standing customers don't need one.
      </p>
      <CodeKeypad value={value} length={5} onChange={(v) => (setValue(v), setError(null))} />
      <p className="error-text" role="alert">
        {error ?? ""}
      </p>
      <div className="row row-end">
        <button className="btn btn-primary" disabled={!value || busy} onClick={save}>
          <Armchair size={22} /> {value ? `TABLE ${value}` : "TYPE A TABLE"}
        </button>
      </div>
    </Modal>
  );
}
