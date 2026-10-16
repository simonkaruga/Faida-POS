import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./shared/theme.css";

// Each screen remembers its own light/dark choice (Owner area > Settings).
try {
  const theme = localStorage.getItem("faida-theme");
  if (theme) document.documentElement.dataset.theme = theme;
} catch {
  // storage unavailable: stay dark
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
