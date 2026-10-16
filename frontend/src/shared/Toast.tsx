import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import "./ui.css";

type Tone = "success" | "warning" | "error";
type ToastItem = { id: number; text: string; tone: Tone };

let next = 1;
const listeners = new Set<(t: ToastItem) => void>();

/** A short confirmation in the corner ("Round sent to T2"). Never for things that need an answer. */
export function toast(text: string, tone: Tone = "success") {
  const item = { id: next++, text, tone };
  listeners.forEach((l) => l(item));
}

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);
  useEffect(() => {
    const add = (t: ToastItem) => {
      setItems((all) => [...all.slice(-2), t]);
      setTimeout(() => setItems((all) => all.filter((x) => x.id !== t.id)), t.tone === "success" ? 3200 : 6000);
    };
    listeners.add(add);
    return () => void listeners.delete(add);
  }, []);
  const Icon = { success: CheckCircle2, warning: AlertTriangle, error: XCircle };
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((t) => {
        const I = Icon[t.tone];
        return (
          <div key={t.id} className={`toast ${t.tone}`}>
            <I size={22} />
            {t.text}
          </div>
        );
      })}
    </div>
  );
}
