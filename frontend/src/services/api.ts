/** Talks to the Faida backend. The session token is kept in memory only, so closing or
 * reloading the screen always returns to the PIN pad. */

export type Role = "owner" | "supervisor" | "waiter";
export type Level = "allow" | "own" | "approval" | "deny";

export type Health = {
  mode: "local" | "cloud";
  version: string;
  set_up: boolean;
  business_name: string | null;
  cloud: "not_linked" | "online" | "offline";
  printers: "not_set_up" | "ok" | "offline";
};

export type Session = {
  token: string;
  staff: { id: string; name: string; role: Role };
  permissions: Record<string, Level>;
  auto_lock_seconds: number;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let token: string | null = null;
let onUnauthorized: () => void = () => {};

export function setToken(value: string | null) {
  token = value;
}

/** Called when the backend says the session has ended (idle, deactivated, restarted). */
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: init.method ?? (init.body ? "POST" : "GET"),
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: init.body ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "The counter is not responding. Check that Faida is running.");
  }
  if (response.status === 401 && token) onUnauthorized();
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === "string" ? data.detail : "Something went wrong.";
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export const login = (pin: string) => api<Session>("/auth/login", { body: { pin } });
export const lock = () => api<void>("/auth/lock", { method: "POST" });
export const getHealth = () => api<Health>("/health");
