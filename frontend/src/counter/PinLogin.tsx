import { useState } from "react";
import type { Notice } from "../App";
import { ApiError, login, type Health, type Session } from "../services/api";
import { Keypad } from "../shared/Keypad";
import "./pin-login.css";

type Props = {
  health: Health | null;
  notice?: Notice | null;
  onLogin: (session: Session) => void;
};

export function PinLogin({ health, notice, onLogin }: Props) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!pin || busy) return;
    setBusy(true);
    try {
      onLogin(await login(pin));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setPin("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="pin-login">
      {notice && <div className={notice.warning ? "lock-message warning" : "lock-message"}>{notice.text}</div>}
      <h1>{health?.business_name ?? "Faida POS"}</h1>
      <p className="pin-prompt">Enter your PIN</p>
      <div className="pin-dots" aria-label={`${pin.length} digits entered`}>
        {Array.from({ length: 6 }, (_, i) => (
          <span key={i} className={i < pin.length ? "pin-dot filled" : "pin-dot"} />
        ))}
      </div>
      <p className="pin-error" role="alert">
        {error ?? " "}
      </p>
      <Keypad
        value={pin}
        onChange={(v) => {
          setPin(v);
          setError(null);
        }}
        onEnter={submit}
        disabled={busy}
      />
    </main>
  );
}
