import { Cloud, CloudOff, HardDrive, Moon, Printer, Sun, SunMoon } from "lucide-react";
import { FaidaMark } from "./Brand";
import { useEffect, useState } from "react";
import type { Health, Role } from "../services/api";
import { initials } from "./look";
import { useThemeChoice, type ThemeChoice } from "./theme";
import "./topbar.css";

type Props = {
  health: Health | null;
  reachable: boolean;
  staff?: { name: string; role: Role };
};

const ROLE = { owner: "Owner", supervisor: "Supervisor", waiter: "Waiter" } as const;
const LOOK = {
  light: { next: "dark", icon: Sun, label: "Bright" },
  dark: { next: "auto", icon: Moon, label: "Dark" },
  auto: { next: "light", icon: SunMoon, label: "Auto" },
} as const satisfies Record<ThemeChoice, { next: ThemeChoice; icon: unknown; label: string }>;

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
  const [look, setLook] = useThemeChoice();
  const LookIcon = LOOK[look].icon;
  const cloud = !reachable
    ? { tone: "red", label: "Counter not responding" }
    : health?.cloud === "online"
      ? { tone: "green", label: "Online" }
      : health?.cloud === "offline"
        ? { tone: "yellow", label: `Offline${health.waiting_to_sync ? ` · ${health.waiting_to_sync} to send` : ""}` }
        : health?.cloud === "off"
          ? { tone: "muted", label: "Counter only" }
          : { tone: "muted", label: "Cloud not linked" };
  const printerTone = health?.printers === "ok" ? "green" : health?.printers === "offline" ? "orange" : "muted";
  const CloudIcon = cloud.tone === "green" ? Cloud : health?.cloud === "off" && reachable ? HardDrive : CloudOff;

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
        <Printer size={18} />{" "}
        {{ ok: "Printers OK", offline: "Printer offline", untested: "Printer: nothing printed yet", not_set_up: "No printer" }[health?.printers ?? "not_set_up"]}
      </span>
      <button
        className="status topbar-look"
        onClick={() => setLook(LOOK[look].next)}
        title="Bright, dark, or auto: dark from 6 pm to 6 am"
        aria-label={`Screen look: ${LOOK[look].label}. Tap to change.`}
      >
        <LookIcon size={18} /> {LOOK[look].label}
      </button>
      <span className="topbar-clock">
        {now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
        <small>{now.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</small>
      </span>
    </header>
  );
}
