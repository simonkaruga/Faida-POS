/** Choices kept on this screen only (each counter PC or tablet decides for itself). */

export type StartScreen = "orders" | "menu";

/** "menu" (the default): after the PIN, staff land on the menu with a new order ready;
 * their other open orders are one tap away above the bill. "orders": they land on the
 * list of their open orders first. */
export function getStartScreen(): StartScreen {
  try {
    return localStorage.getItem("faida-start") === "orders" ? "orders" : "menu";
  } catch {
    return "menu";
  }
}

export function setStartScreen(value: StartScreen) {
  try {
    localStorage.setItem("faida-start", value);
  } catch {
    // not remembered on this screen; it opens on the menu
  }
}
