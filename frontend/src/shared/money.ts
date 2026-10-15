const ksh = new Intl.NumberFormat("en-KE", { maximumFractionDigits: 0 });

/** Shillings as shown everywhere in Faida: "2,100". */
export function formatKsh(amount: number): string {
  return ksh.format(Math.round(amount));
}
