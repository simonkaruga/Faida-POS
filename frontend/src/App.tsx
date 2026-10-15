import { useCallback, useEffect, useState } from "react";
import { OrderScreen } from "./counter/OrderScreen";
import { PayScreen } from "./counter/PayScreen";
import { PinLogin } from "./counter/PinLogin";
import { TablesScreen } from "./counter/TablesScreen";
import { useAutoLock } from "./counter/useAutoLock";
import "./counter/counter.css";
import { getMenu, lock, setToken, setUnauthorizedHandler, type Menu, type Session } from "./services/api";
import { useHealth } from "./services/useHealth";
import { TopBar } from "./shared/TopBar";

export type Notice = { text: string; warning?: boolean };
type View = { screen: "tables" } | { screen: "order"; billId: string } | { screen: "pay"; billId: string };

function SignedIn({ session, onLock }: { session: Session; onLock: (notice?: Notice) => void }) {
  useAutoLock(session.auto_lock_seconds, () => onLock());
  const [view, setView] = useState<View>({ screen: "tables" });
  const [menu, setMenu] = useState<Menu | null>(null);

  useEffect(() => {
    getMenu().then(setMenu, () => {});
  }, []);

  const tables = () => setView({ screen: "tables" });
  // Auto-lock after each SEND and each completed payment (masterplan 4.4).
  const lockWith = (text: string, warning?: boolean) => onLock({ text, warning });

  switch (view.screen) {
    case "order":
      if (!menu) return <main className="screen-center">Loading menu…</main>;
      return (
        <OrderScreen
          key={view.billId}
          session={session}
          menu={menu}
          billId={view.billId}
          onBack={tables}
          onPay={(billId) => setView({ screen: "pay", billId })}
          onOpen={(billId) => setView({ screen: "order", billId })}
          onSent={lockWith}
        />
      );
    case "pay":
      return (
        <PayScreen
          session={session}
          billId={view.billId}
          onBack={() => setView({ screen: "order", billId: view.billId })}
          onDone={lockWith}
        />
      );
    default:
      return (
        <TablesScreen
          session={session}
          onOpen={(billId) => setView({ screen: "order", billId })}
          onLock={() => onLock()}
        />
      );
  }
}

export function App() {
  const { health, reachable } = useHealth();
  const [session, setSession] = useState<Session | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const signOut = useCallback(() => {
    setToken(null);
    setSession(null);
  }, []);

  const doLock = useCallback(
    (n?: Notice) => {
      lock().catch(() => {});
      signOut();
      setNotice(n ?? null);
    },
    [signOut],
  );

  useEffect(() => setUnauthorizedHandler(signOut), [signOut]);

  const onLogin = (s: Session) => {
    setToken(s.token);
    setSession(s);
    setNotice(null);
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
        <PinLogin health={health} notice={notice} onLogin={onLogin} />
      )}
    </>
  );
}
