import type { Session } from "../services/api";
import "./home.css";

type Props = {
  session: Session;
  onLock: () => void;
};

const ROLE_NAMES = { owner: "Owner", supervisor: "Supervisor", waiter: "Waiter" } as const;

/** The waiter's home screen. Tables, orders and payments arrive in Phase 2. */
export function Home({ session, onLock }: Props) {
  return (
    <main className="home">
      <section className="home-body">
        <h2>Karibu, {session.staff.name}</h2>
        <p className="home-role">{ROLE_NAMES[session.staff.role]}</p>
        <p className="home-note">Tables, orders and payments will appear here.</p>
      </section>
      <footer className="home-actions">
        <button className="btn btn-primary" onClick={onLock}>
          LOCK
        </button>
      </footer>
    </main>
  );
}
