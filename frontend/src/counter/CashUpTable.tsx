import type { CashUp } from "../services/api";
import { formatKsh } from "../shared/money";

/** The cash-up as in masterplan 4.6. Lines for cash taken on other people's bills only
 * appear when there is any (e.g. after a bill was handed over part-paid). */
export function CashUpTable({ cash }: { cash: CashUp }) {
  const row = (label: string, amount: number, className = "") => (
    <div className={`cashup-row ${className}`}>
      <span>{label}</span>
      <span>{formatKsh(amount)}</span>
    </div>
  );
  return (
    <div className="cashup">
      {row(`Total sales (${cash.bills} ${cash.bills === 1 ? "bill" : "bills"})`, cash.total_sales)}
      {row("− Paid by M-Pesa", cash.mpesa)}
      {row("− Approved credit", cash.credit)}
      {cash.cash_taken_by_others > 0 && row("− Cash taken by others on your bills", cash.cash_taken_by_others)}
      {row("= Cash due from sales", cash.cash_due_from_sales, "subtotal")}
      <div className="cashup-row note">
        <span>of which unpaid – your responsibility</span>
        <span>{formatKsh(cash.unpaid_responsible)}</span>
      </div>
      {cash.cash_taken_for_others > 0 && row("+ Cash you took on others' bills", cash.cash_taken_for_others)}
      {row("+ Float received at start", cash.float_amount)}
      {row("− M-Pesa tips (yours, in cash)", cash.mpesa_tips)}
      {row("= CASH TO HAND OVER", cash.cash_to_hand_over, "grand")}
    </div>
  );
}
