import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./shared/theme.css";

// Bright unless this screen was switched to dark (Owner area > Settings).
let theme = "light";
try {
  theme = localStorage.getItem("faida-theme") ?? "light";
} catch {
  // storage unavailable: stay bright
}
document.documentElement.dataset.theme = theme;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
