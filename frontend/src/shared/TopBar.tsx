import { Cloud, CloudOff, Printer } from "lucide-react";
import { FaidaMark } from "./Brand";
import { useEffect, useState } from "react";
import type { Health, Role } from "../services/api";
import { initials } from "./look";
import "./topbar.css";

type Props = {
  health: Health | null;
  reachable: boolean;
  staff?: { name: string; role: Role };
};

const ROLE = { owner: "Owner", supervisor: "Supervisor", waiter: "Waiter" } as const;

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 15_000);
    return () => clearInterval(id);
  }, []);
  return now;
}

/** Always shows status (masterplan 9.2 rule 7): who is working, cloud, printers, time. */
export function TopBar({ health, reachable, staff }: Props) {
  const now = useClock();
  const cloud = !reachable
    ? { tone: "red", label: "Counter not responding" }
    : health?.cloud === "online"
      ? { tone: "green", label: "Online" }
      : health?.cloud === "offline"
        ? { tone: "yellow", label: `Offline${health.waiting_to_sync ? ` · ${health.waiting_to_sync} to send` : ""}` }
        : { tone: "muted", label: "Cloud not linked" };
  const printerTone = health?.printers === "ok" ? "green" : health?.printers === "offline" ? "orange" : "muted";
  const CloudIcon = cloud.tone === "green" ? Cloud : CloudOff;

  return (
    <header className="topbar">
      <span className="brand">
        <FaidaMark size={36} />
        {health?.business_name ?? "Faida POS"}
      </span>
      {staff && (
        <span className="topbar-staff">
          <span className="avatar">{initials(staff.name)}</span>
          <span>
            {staff.name}
            <small>{ROLE[staff.role]}</small>
          </span>
        </span>
      )}
      <span className="topbar-spacer" />
      <span className={`status ${cloud.tone}`}>
        <CloudIcon size={18} /> {cloud.label}
      </span>
      <span className={`status ${printerTone}`}>
        <Printer size={18} /> {health?.printers === "ok" ? "Printers OK" : health?.printers === "offline" ? "Printer offline" : "No printer"}
      </span>
      <span className="topbar-clock">
        {now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
        <small>{now.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</small>
      </span>
    </header>
  );
}
