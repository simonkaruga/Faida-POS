import { CheckCircle2, Clock3, Printer, Smartphone, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../services/api";
import { Modal } from "./Modal";
import "./receipt.css";

/** One printed row, exactly as the backend prints it (app/printing/document.py). */
export type DocRow = {
  text?: string;
  cols?: [string, string];
  rule?: boolean;
  size?: number;
  bold?: boolean;
  align?: "left" | "center" | "right";
};

export type Printout = {
  id: string;
  kind: "bar_slip" | "kitchen_ticket" | "bill" | "receipt" | "handover";
  number: number;
  printer: "counter" | "kitchen";
  status: "pending" | "printed" | "not_printed";
  created_at: string;
  printed_at: string | null;
  reprints: number;
  last_error: string | null;
  title: string;
};
export type PrintoutDoc = Printout & { copies: (string | null)[]; content: DocRow[] };

export const getPrintout = (id: string) => api<PrintoutDoc>(`/tickets/${id}`);
export const getPrintouts = () => api<Printout[]>("/printouts");

export const KIND_NAME: Record<Printout["kind"], string> = {
  bar_slip: "Bar slip",
  kitchen_ticket: "Kitchen ticket",
  bill: "Bill",
  receipt: "Receipt",
  handover: "Hand-over slip",
};

const WIDTH = 48; // characters on an 80 mm printer

function rowLines(row: DocRow): string[] {
  const width = Math.floor(WIDTH / (row.size ?? 1));
  if (row.rule) return ["-".repeat(WIDTH)];
  if (row.cols) {
    const [left, right] = row.cols;
    const room = Math.max(1, width - right.length - 1);
    const lines: string[] = [];
    let rest = left;
    while (rest.length > room) {
      lines.push(rest.slice(0, room));
      rest = rest.slice(room);
    }
    lines.push(rest.padEnd(width - right.length) + right);
    return lines;
  }
  return [row.text ?? ""];
}

/** The receipt on paper, the same 48 columns as the thermal printer. */
export function Paper({ rows, copy }: { rows: DocRow[]; copy?: string | null }) {
  return (
    <div className="paper" role="document">
      {copy && <div className="paper-row center bold">*** {copy} ***</div>}
      {rows.map((row, i) =>
        rowLines(row).map((line, j) => (
          <div key={`${i}-${j}`} className={`paper-row ${row.align ?? "left"} ${row.bold ? "bold" : ""} ${row.size === 2 ? "big" : ""} ${row.rule ? "rule" : ""}`}>
            {line}
          </div>
        )),
      )}
    </div>
  );
}

/** Print on the device showing the screen (a desk printer, or "Save as PDF"), for
 * when the thermal printer isn't there. */
export function printHere(doc: PrintoutDoc) {
  const escape = (s: string) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!);
  const copies = doc.copies.length ? doc.copies : [null];
  const body = copies
    .map((copy) => {
      const rows = (copy ? [{ text: `*** ${copy} ***`, align: "center", bold: true } as DocRow] : []).concat(doc.content);
      const html = rows
        .flatMap((row) => rowLines(row).map((line) => `<div class="${row.align ?? "left"} ${row.bold ? "b" : ""} ${row.size === 2 ? "big" : ""}">${escape(line) || "&nbsp;"}</div>`))
        .join("");
      return `<section>${html}</section>`;
    })
    .join("");
  const frame = document.createElement("iframe");
  frame.style.cssText = "position:fixed;width:0;height:0;border:0;right:0;bottom:0";
  document.body.appendChild(frame);
  const w = frame.contentWindow!;
  w.document.write(`<!doctype html><html><head><title>${escape(doc.title)}</title><style>
    @page { size: 80mm auto; margin: 4mm; }
    body { margin: 0; font: 12px/1.35 ui-monospace, Menlo, Consolas, monospace; color: #000; }
    section { white-space: pre; page-break-after: always; }
    .center { text-align: center; } .right { text-align: right; } .b { font-weight: 700; }
    .big { font-size: 22px; font-weight: 700; letter-spacing: 1px; }
  </style></head><body>${body}</body></html>`);
  w.document.close();
  w.focus();
  w.print();
  setTimeout(() => frame.remove(), 60_000);
}

export function StatusPill({ status }: { status: Printout["status"] }) {
  if (status === "printed")
    return (
      <span className="pill green">
        <CheckCircle2 size={14} /> Printed
      </span>
    );
  if (status === "pending")
    return (
      <span className="pill blue">
        <Clock3 size={14} /> Printing…
      </span>
    );
  return (
    <span className="pill orange">
      <TriangleAlert size={14} /> Not printed
    </span>
  );
}

/** Shows a printout as it was printed, with its copies, and lets staff print it again. */
export function ReceiptPreview({
  id,
  onReprint,
  compact,
  free,
}: {
  id: string;
  /** Print again on the counter printer (the caller handles approval rules). */
  onReprint?: () => Promise<unknown>;
  compact?: boolean;
  /** Owner or supervisor: may print a copy on this device even if it already printed.
   * Others only when it never came out, so an extra slip can't mean an extra drink. */
  free?: boolean;
}) {
  const [doc, setDoc] = useState<PrintoutDoc | null>(null);
  const [copy, setCopy] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const load = () => getPrintout(id).then(setDoc, (e) => setError(e instanceof ApiError ? e.message : "Couldn't load it."));
  useEffect(() => {
    load();
    // Pick up the printer's answer if it was still printing.
    const t = setTimeout(load, 2500);
    return () => clearTimeout(t);
  }, [id]);

  if (!doc) return <div className="screen-loading">{error ?? <span className="spinner" />}</div>;
  const copies = doc.copies.length ? doc.copies : [null];
  return (
    <div className={`receipt-view ${compact ? "compact" : ""}`}>
      <div className="receipt-meta">
        <strong>
          {KIND_NAME[doc.kind]} {doc.kind === "receipt" ? `No. ${String(doc.number).padStart(4, "0")}` : doc.number}
        </strong>
        <StatusPill status={doc.status} />
        {doc.reprints > 0 && <span className="pill">reprinted {doc.reprints}×</span>}
      </div>
      {copies.length > 1 && (
        <div className="copy-tabs">
          {copies.map((c, i) => (
            <button key={i} className={copy === i ? "on" : ""} onClick={() => setCopy(i)}>
              {c ?? "Customer copy"}
            </button>
          ))}
        </div>
      )}
      <div className="paper-wrap">
        <Paper rows={doc.content} copy={copies[copy]} />
      </div>
      {doc.last_error && doc.status === "not_printed" && <p className="warn" style={{ margin: 0 }}>Printer said: {doc.last_error}</p>}
      <div className="row">
        {onReprint && (
          <button className="btn btn-quiet grow" onClick={() => onReprint().then(load, (e) => setError(e instanceof ApiError ? e.message : "Couldn't reprint."))}>
            <Printer size={20} /> Print again
          </button>
        )}
        {(free || doc.status !== "printed") && (
          <button className="btn btn-quiet grow" onClick={() => printHere(doc)}>
            <Smartphone size={20} /> Print here
          </button>
        )}
      </div>
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}

export function ReceiptDialog({
  id,
  title,
  onReprint,
  onClose,
  free,
}: {
  id: string;
  title: string;
  onReprint?: () => Promise<unknown>;
  onClose: () => void;
  free?: boolean;
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <ReceiptPreview id={id} onReprint={onReprint} free={free} />
    </Modal>
  );
}
