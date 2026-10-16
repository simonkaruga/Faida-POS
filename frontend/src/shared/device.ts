/** Choices kept on this screen only (each counter PC or tablet decides for itself). */

export type StartScreen = "orders" | "menu";

/** "orders": a waiter's screen opens on their open orders. "menu": a counter screen
 * opens straight on the menu with a new order, for selling at the bar. */
export function getStartScreen(): StartScreen {
  try {
    return localStorage.getItem("faida-start") === "menu" ? "menu" : "orders";
  } catch {
    return "orders";
  }
}

export function setStartScreen(value: StartScreen) {
  try {
    localStorage.setItem("faida-start", value);
  } catch {
    // not remembered on this screen; it opens on orders
  }
}
