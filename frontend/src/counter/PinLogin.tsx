import { CheckCircle2, LockKeyhole, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import type { Notice } from "../App";
import { ApiError, login, type Health, type Session } from "../services/api";
import { Keypad } from "../shared/Keypad";
import "./pin-login.css";

type Props = {
  health: Health | null;
  notice?: Notice | null;
  onLogin: (session: Session) => void;
};

function useNow() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 10_000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export function PinLogin({ health, notice, onLogin }: Props) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [shake, setShake] = useState(0);
  const [busy, setBusy] = useState(false);
  const now = useNow();

  const submit = async () => {
    if (!pin || busy) return;
    setBusy(true);
    try {
      onLogin(await login(pin));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setPin("");
      setShake((n) => n + 1);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="pin-login">
      <section className="pin-brand">
        <div className="pin-time">{now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</div>
        <div className="pin-date">{now.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}</div>
        <h1>{health?.business_name ?? "Faida POS"}</h1>
        {notice && (
          <div className={notice.warning ? "lock-message warning" : "lock-message"} key={notice.text}>
            {notice.warning ? <TriangleAlert size={24} /> : <CheckCircle2 size={24} />}
            {notice.text}
          </div>
        )}
        <p className="pin-hint">Every action is recorded under your PIN. Never share it.</p>
      </section>
      <section className="pin-pad">
        <div className="pin-lock">
          <LockKeyhole size={26} />
        </div>
        <p className="pin-prompt">Enter your PIN</p>
        <div className="pin-dots" aria-label={`${pin.length} digits entered`} key={shake} data-shake={shake > 0}>
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
      </section>
    </main>
  );
}
