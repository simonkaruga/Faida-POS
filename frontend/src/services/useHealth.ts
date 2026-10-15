import { useEffect, useState } from "react";
import { getHealth, type Health } from "./api";

/** Polls the backend status every 10 seconds for the top bar and PIN screen. */
export function useHealth(intervalMs = 10_000) {
  const [health, setHealth] = useState<Health | null>(null);
  const [reachable, setReachable] = useState(true);

  useEffect(() => {
    let alive = true;
    const check = () =>
      getHealth()
        .then((h) => alive && (setHealth(h), setReachable(true)))
        .catch(() => alive && setReachable(false));
    check();
    const id = setInterval(check, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [intervalMs]);

  return { health, reachable };
}
