import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../shared/theme.css";
import { PhoneApp } from "./PhoneApp";

// The counter is dark for a dim bar; the phone follows the phone's own setting.
const light = window.matchMedia("(prefers-color-scheme: light)");
const applyTheme = () => {
  document.documentElement.dataset.theme = light.matches ? "light" : "dark";
};
applyTheme();
light.addEventListener("change", applyTheme);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PhoneApp />
  </StrictMode>,
);
