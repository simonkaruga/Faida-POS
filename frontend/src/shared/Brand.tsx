import "./brand.css";
import mark from "./brand/faida-mark.png";
import wordmark from "./brand/faida-wordmark.png";
import wordmarkDark from "./brand/faida-wordmark-dark.png";

/** Avinaya's support line, the same for every Faida client. Shown as text, not a link:
 * a link would take the full-screen counter away from Faida. */
export const SUPPORT_PHONE = "+254 797 033 513";

/** The Faida mark on its white tile (the receipt inside it is white paper, so the tile
 * keeps it readable on dark screens). */
export function FaidaMark({ size = 34, className = "" }: { size?: number; className?: string }) {
  return (
    <span className={`faida-mark ${className}`} style={{ width: size, height: size }} aria-hidden>
      <img src={mark} alt="" draggable={false} />
    </span>
  );
}

/** "FAIDA POS" in the brand colours, with white lettering on the dark theme. */
export function FaidaWordmark({ height = 28, className = "" }: { height?: number; className?: string }) {
  return (
    <span className={`faida-wordmark ${className}`} role="img" aria-label="Faida POS" style={{ height }}>
      <img className="on-dark" src={wordmarkDark} alt="" draggable={false} />
      <img className="on-light" src={wordmark} alt="" draggable={false} />
    </span>
  );
}

/** Mark and wordmark together, as on the logo. */
export function FaidaLogo({ height = 44, className = "" }: { height?: number; className?: string }) {
  return (
    <span className={`faida-logo ${className}`}>
      <FaidaMark size={height} />
      <FaidaWordmark height={Math.round(height * 0.8)} />
    </span>
  );
}
