import { useEffect, useState } from "react";
import type { Health } from "../services/api";
import "./topbar.css";

type Props = {
  health: Health | null;
  reachable: boolean;
  staffName?: string;
};

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 15_000);
    return () => clearInterval(id);
  }, []);
  return now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** Always shows status (masterplan 9.2 rule 7): who is working, cloud, printers, time. */
export function TopBar({ health, reachable, staffName }: Props) {
  const clock = useClock();
  const cloud = !reachable
    ? { tone: "red", label: "Counter not responding" }
    : health?.cloud === "online"
      ? { tone: "green", label: "Online" }
      : { tone: "yellow", label: health?.cloud === "offline" ? "Offline" : "Cloud not linked" };
  const printers = health?.printers === "ok" ? "OK" : "Not set up";

  return (
    <header className="topbar">
      <span className="topbar-business">{health?.business_name ?? "Faida POS"}</span>
      {staffName && <span className="topbar-staff">{staffName}</span>}
      <span className="topbar-spacer" />
      <span className="topbar-status">
        <span className={`dot dot-${cloud.tone}`} aria-hidden /> {cloud.label}
      </span>
      <span className="topbar-status">🖨 {printers}</span>
      <span className="topbar-clock">{clock}</span>
    </header>
  );
}
