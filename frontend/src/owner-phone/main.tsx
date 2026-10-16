import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../shared/theme.css";
import { PhoneApp } from "./PhoneApp";

// Bright, like the counter: easy to read outdoors.
document.documentElement.dataset.theme = "light";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PhoneApp />
  </StrictMode>,
);
