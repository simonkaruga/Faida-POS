import "./keypad.css";

const ROWS = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"];

type Props = {
  value: string;
  length: number;
  onChange: (value: string) => void;
};

/** Large letter and number keys for typing an M-Pesa code (masterplan 9.4). */
export function CodeKeypad({ value, length, onChange }: Props) {
  const press = (c: string) => value.length < length && onChange(value + c);
  return (
    <div className="code-keypad">
      <div className="code-boxes" aria-label={`M-Pesa code ${value}`}>
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
