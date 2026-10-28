import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./shared/theme.css";
import { startTheme } from "./shared/theme";

// Bright unless this screen was switched to dark or auto (top bar, or Owner area > Settings).
startTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
