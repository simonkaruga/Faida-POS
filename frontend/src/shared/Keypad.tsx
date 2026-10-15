import { useEffect } from "react";
import "./keypad.css";

type Props = {
  value: string;
  onChange: (value: string) => void;
  onEnter: () => void;
  maxLength?: number;
  disabled?: boolean;
  enterLabel?: string;
};

/** Large number keypad (keys ≥ 72 px, masterplan 9.1). Also accepts a physical keyboard. */
export function Keypad({ value, onChange, onEnter, maxLength = 6, disabled, enterLabel = "OK" }: Props) {
  const press = (digit: string) => {
    if (!disabled && value.length < maxLength) onChange(value + digit);
  };
  const back = () => !disabled && onChange(value.slice(0, -1));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (disabled || e.target instanceof HTMLInputElement) return;
      if (/^\d$/.test(e.key)) press(e.key);
      else if (e.key === "Backspace") back();
      else if (e.key === "Enter" && value) onEnter();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="keypad">
      {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((d) => (
        <button key={d} className="key" onClick={() => press(d)} disabled={disabled}>
          {d}
        </button>
      ))}
      <button className="key key-quiet" onClick={back} disabled={disabled} aria-label="Delete">
        ⌫
      </button>
      <button className="key" onClick={() => press("0")} disabled={disabled}>
        0
      </button>
      <button className="key key-enter" onClick={onEnter} disabled={disabled || !value}>
        {enterLabel}
      </button>
    </div>
  );
}
