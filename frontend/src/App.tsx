import { useCallback, useEffect, useState } from "react";
import { EndShift } from "./counter/EndShift";
import { FinishedBills } from "./counter/FinishedBills";
import { HomeScreen } from "./counter/HomeScreen";
import { OrderScreen } from "./counter/OrderScreen";
import { OwnerArea } from "./counter/OwnerArea";
import { PayScreen } from "./counter/PayScreen";
import { PinLogin } from "./counter/PinLogin";
import { TablesScreen } from "./counter/TablesScreen";
import { useAutoLock } from "./counter/useAutoLock";
import "./counter/counter.css";
import { getMenu, lock, openBill, setToken, setUnauthorizedHandler, type Menu, type Session } from "./services/api";
import { useHealth } from "./services/useHealth";
import { Toaster } from "./shared/Toast";
import { FaidaLogo } from "./shared/Brand";
import { getStartScreen } from "./shared/device";
import { TopBar } from "./shared/TopBar";

export type Notice = { text: string; warning?: boolean };
type View =
  | { screen: "home" | "floor" | "endShift" | "myBills" | "owner" | "starting" }
  | { screen: "order"; billId: string }
  | { screen: "pay"; billId: string };

// Idle lock for counting a hand-over or reading the owner panel (5 minutes).
const COUNTING_IDLE_SECONDS = 300;

function SignedIn({ session, onLock }: { session: Session; onLock: (notice?: Notice) => void }) {
  // The owner lands on her own panel (dashboard); staff on their orders. A counter screen
  // set to "menu" opens staff straight on a new order (an empty one is reused).
  const [view, setView] = useState<View>({
    screen: session.staff.role === "owner" ? "owner" : getStartScreen() === "menu" ? "starting" : "home",
  });
  useEffect(() => {
    if (view.screen === "starting")
      openBill().then((b) => setView({ screen: "order", billId: b.id }), () => setView({ screen: "home" }));
  }, [view.screen]);
  // Counting a hand-over, or reading reports in the owner panel, takes longer than the till's idle lock.
  const slow = view.screen === "endShift" || view.screen === "owner";
  useAutoLock(slow ? Math.max(session.auto_lock_seconds, COUNTING_IDLE_SECONDS) : session.auto_lock_seconds, () => onLock());
  const [menu, setMenu] = useState<Menu | null>(null);

  const reloadMenu = useCallback(() => getMenu().then(setMenu, () => {}), []);
  useEffect(() => {
    reloadMenu();
  }, [reloadMenu]);

  const tables = () => setView({ screen: "home" });
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
          onMenuChanged={reloadMenu}
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
    case "endShift":
      return <EndShift session={session} onPay={(billId) => setView({ screen: "pay", billId })} onBack={tables} onDone={lockWith} />;
    case "myBills":
      return (
        <main className="screen">
          <div className="screen-scroll">
            <h2 className="section-title">My finished bills this shift</h2>
            <FinishedBills session={session} embedded />
          </div>
          <footer className="screen-actions">
            <button className="btn btn-quiet" onClick={tables}>
              ‹ Orders
            </button>
          </footer>
        </main>
      );
    case "owner":
      return <OwnerArea session={session} onBack={tables} onLock={() => onLock()} />;
    case "starting":
      return <main className="screen screen-loading"><span className="spinner" /> New order…</main>;
    case "floor":
      return (
        <TablesScreen
          session={session}
          onOpen={(billId) => setView({ screen: "order", billId })}
          onNavigate={(screen) => setView({ screen })}
          onLock={() => onLock()}
        />
      );
    default:
      return (
        <HomeScreen
          session={session}
          onOpen={(billId) => setView({ screen: "order", billId })}
          onPay={(billId) => setView({ screen: "pay", billId })}
          onNavigate={(screen) => setView({ screen })}
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
      <TopBar health={health} reachable={reachable} staff={session?.staff} />
      <Toaster />
      {health && !health.set_up ? (
        <main className="pin-login">
          <div className="pin-setup">
            <FaidaLogo height={64} />
            <h1>This counter is not set up yet</h1>
            <p className="pin-prompt">Run the install steps in docs/install-checklist.md.</p>
          </div>
        </main>
      ) : session ? (
        <SignedIn session={session} onLock={doLock} />
      ) : (
        <PinLogin health={health} notice={notice} onLogin={onLogin} />
      )}
    </>
  );
}
