/** The phone view talks to the cloud. In development the cloud runs separately and is
 * reached through the dev server's /cloud proxy. */

import type { ClosingReport, Profit, SalesSummary } from "../services/api";

const BASE = import.meta.env.DEV ? "/cloud/api/phone" : "/api/phone";
const KEY = "faida-owner-token";

export class PhoneError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// Kept for this browser tab only, so closing the tab logs out.
export const savedToken = () => {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
};
export const saveToken = (token: string | null) => {
  try {
    if (token) sessionStorage.setItem(KEY, token);
    else sessionStorage.removeItem(KEY);
  } catch {
    // private mode: the login just won't survive a reload
  }
};

let onLoggedOut = () => {};
export const setLoggedOutHandler = (fn: () => void) => (onLoggedOut = fn);

async function call<T>(path: string, init: { body?: unknown } = {}): Promise<T> {
  const token = savedToken();
  let r: Response;
  try {
    r = await fetch(`${BASE}${path}`, {
      method: init.body ? "POST" : "GET",
      headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: init.body ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new PhoneError(0, "No connection. Check your internet.");
  }
  if (r.status === 401 && token) {
    saveToken(null);
    onLoggedOut();
  }
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new PhoneError(r.status, typeof data.detail === "string" ? data.detail : "Something went wrong.");
  }
  return r.json();
}

type Fresh = { last_updated: string | null };
export type Today = Fresh & {
  business_name: string;
  day: string;
  sales: SalesSummary;
  credit_collected: { total: number };
  shortages: { staff: string; difference: number }[];
  voids: { count: number; total: number };
  low_stock: { item: string; level: string }[];
  check_stock: { item: string; level: string }[];
  open_shifts: string[];
  closed: boolean;
  alerts: string[];
};
export type PhoneClosing = Fresh & { day: string; closed: boolean; cash_box_counted: number | null; report: ClosingReport };
export type PhoneStock = Fresh & {
  low: { item: string; level: string }[];
  check: { item: string; level: string }[];
  value: number;
  variance: { day: string; item: string; variance: string; value: number }[];
};
export type PhoneProfit = Fresh & {
  start: string;
  end: string;
  profit: Profit;
  sales: SalesSummary;
  shortages: { staff: string; shifts: number; times_short: number; short: number }[];
};
export type PhoneDebtors = Fresh & { total: number; debtors: { name: string; phone: string | null; owed: number; limit: number; since: string | null }[] };

export const login = (email: string, password: string, code: string) =>
  call<{ token: string; business_name: string | null }>("/login", { body: { email, password, code } });
export const getToday = () => call<Today>("/today");
export const getClosing = (day?: string) => call<PhoneClosing>(`/closing${day ? `?day=${day}` : ""}`);
export const getStock = () => call<PhoneStock>("/stock");
export const getProfit = (start?: string, end?: string) => call<PhoneProfit>(`/profit${start ? `?start=${start}&end=${end}` : ""}`);
export const getDebtors = () => call<PhoneDebtors>("/debtors");
