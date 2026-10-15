import { useEffect, useRef } from "react";

/** Calls `onLock` after `seconds` with no touch or key press (masterplan 4.4). */
export function useAutoLock(seconds: number, onLock: () => void) {
  const lockRef = useRef(onLock);
  lockRef.current = onLock;

  useEffect(() => {
    let timer = setTimeout(() => lockRef.current(), seconds * 1000);
    const reset = () => {
      clearTimeout(timer);
      timer = setTimeout(() => lockRef.current(), seconds * 1000);
    };
    const events = ["pointerdown", "keydown"] as const;
    events.forEach((e) => window.addEventListener(e, reset));
    return () => {
      clearTimeout(timer);
      events.forEach((e) => window.removeEventListener(e, reset));
    };
  }, [seconds]);
}
