import { CheckCircle2, LockKeyhole, ShieldCheck, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import type { Notice } from "../App";
import { ApiError, login, type Health, type Session } from "../services/api";
import logo from "../shared/brand/faida-logo.png";
import { Keypad } from "../shared/Keypad";
import "./pin-login.css";

type Props = {
  health: Health | null;
  notice?: Notice | null;
  onLogin: (session: Session) => void;
};

function greeting(now: Date) {
  const h = now.getHours();
  return h >= 5 && h < 12 ? "Good morning" : h >= 12 && h < 17 ? "Good afternoon" : "Good evening";
}

function useNow() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 10_000);
    return () => clearInterval(id);
  }, []);
  return now;
}

/** A cube drawn in CSS 3D: six faces in the logo's colours (see pin-login.css). */
function Cube({ className }: { className: string }) {
  return (
    <span className={className}>
      {["front", "back", "right", "left", "top", "bottom"].map((f) => (
        <span key={f} className={`face ${f}`} />
      ))}
    </span>
  );
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
      <div className="pin-scene" aria-hidden>
        <span className="orb orb-orange" />
        <span className="orb orb-blue" />
        <span className="orb orb-navy" />
        <span className="ring" />
        <Cube className="cube cube-big" />
        <Cube className="cube cube-small" />
        <span className="glass-tile" />
      </div>
      <section className="pin-brand">
        <div className="pin-logo-card">
          <img src={logo} alt="Faida POS" draggable={false} />
        </div>
        <div className="pin-business">
          <h1>{health?.business_name ?? "Faida POS"}</h1>
          <span>
            Karibu · {greeting(now)} · {now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })},{" "}
            {now.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}
          </span>
        </div>
        {notice && (
          <div className={notice.warning ? "lock-message warning" : "lock-message"} key={notice.text}>
            {notice.warning ? <TriangleAlert size={24} /> : <CheckCircle2 size={24} />}
            {notice.text}
          </div>
        )}
        <p className="pin-hint">
          <ShieldCheck size={18} /> Every action is recorded under your PIN. Never share it.
        </p>
      </section>
      <section className="pin-pad">
        <div className="pin-card">
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
        </div>
      </section>
    </main>
  );
}
