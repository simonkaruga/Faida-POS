import { useEffect } from "react";
import "./keypad.css";

const ROWS = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"];

type Props = {
  value: string;
  length: number;
  onChange: (value: string) => void;
  /** Enter on a physical keyboard, e.g. to save. */
  onEnter?: () => void;
  /** Off where a number keypad on the same screen already takes the typed digits. */
  keyboard?: boolean;
};

/** Large letter and number keys for typing an M-Pesa code (masterplan 9.4). Also accepts
 * a physical keyboard, for counters with a mouse instead of a touch screen. */
export function CodeKeypad({ value, length, onChange, onEnter, keyboard = true }: Props) {
  const press = (c: string) => value.length < length && onChange(value + c);

  useEffect(() => {
    if (!keyboard) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.altKey || e.metaKey || e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (/^[a-z0-9]$/i.test(e.key)) press(e.key.toUpperCase());
      else if (e.key === "Backspace") onChange(value.slice(0, -1));
      else if (e.key === "Enter" && value && onEnter) onEnter();
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="code-keypad">
      <div className="code-boxes" aria-label={`Code typed: ${value}`}>
        {Array.from({ length }, (_, i) => (
          <span key={i} className={i === value.length ? "code-box current" : "code-box"}>
            {value[i] ?? ""}
          </span>
        ))}
      </div>
      {ROWS.map((row) => (
        <div key={row} className="code-row">
          {row.split("").map((c) => (
            <button key={c} className="key code-key" onClick={() => press(c)}>
              {c}
            </button>
          ))}
        </div>
      ))}
      <div className="code-row">
        <button className="key key-quiet code-wide" onClick={() => onChange(value.slice(0, -1))} aria-label="Delete">
          ⌫
        </button>
        <button className="key key-quiet code-wide" onClick={() => onChange("")}>
          Clear
        </button>
      </div>
    </div>
  );
}
