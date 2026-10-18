import { FileText, Printer, ReceiptText } from "lucide-react";
import { useState } from "react";
import { ApiError, printSlip, type SlipKind } from "../services/api";
import { toast } from "./Toast";

/** Print this page on paper (A4) or save it as a PDF: the browser's print dialog, with
 * the owner screens' menus and buttons hidden by the print stylesheet. */
export function PrintPageButton() {
  return (
    <button className="btn btn-quiet no-print" onClick={() => window.print()}>
      <FileText size={20} /> Print / PDF
    </button>
  );
}

/** Print a short version on the counter's receipt printer. */
export function SlipButton({ kind, day, label }: { kind: SlipKind; day?: string; label: string }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const { status } = await printSlip(kind, day);
      if (status === "printed") toast(`${label}: printed`);
      else if (status === "pending") toast(`${label}: sent to the printer`);
      else toast(`${label} did NOT print. Check the receipt printer.`, "warning");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Something went wrong.", "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <button className="btn btn-quiet no-print" onClick={go} disabled={busy}>
      {kind === "closing" ? <ReceiptText size={20} /> : <Printer size={20} />} {label}
    </button>
  );
}
