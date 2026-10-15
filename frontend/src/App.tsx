import { useCallback, useEffect, useState } from "react";
import { Home } from "./counter/Home";
import { PinLogin } from "./counter/PinLogin";
import { useAutoLock } from "./counter/useAutoLock";
import { lock, setToken, setUnauthorizedHandler, type Session } from "./services/api";
import { useHealth } from "./services/useHealth";
import { TopBar } from "./shared/TopBar";

function SignedIn({ session, onLock }: { session: Session; onLock: () => void }) {
  useAutoLock(session.auto_lock_seconds, onLock);
  return <Home session={session} onLock={onLock} />;
}

export function App() {
  const { health, reachable } = useHealth();
  const [session, setSession] = useState<Session | null>(null);

  const signOut = useCallback(() => {
    setToken(null);
    setSession(null);
  }, []);

  const doLock = useCallback(() => {
    lock().catch(() => {});
    signOut();
  }, [signOut]);

  useEffect(() => setUnauthorizedHandler(signOut), [signOut]);

  const onLogin = (s: Session) => {
    setToken(s.token);
    setSession(s);
  };

  return (
    <>
      <TopBar health={health} reachable={reachable} staffName={session?.staff.name} />
      {health && !health.set_up ? (
        <main className="pin-login">
          <h1>This counter is not set up yet</h1>
          <p className="pin-prompt">Run the install steps in docs/install-checklist.md.</p>
        </main>
      ) : session ? (
        <SignedIn session={session} onLock={doLock} />
      ) : (
        <PinLogin health={health} onLogin={onLogin} />
      )}
    </>
  );
}
