/** The round being built, before SEND. Kept in memory per waiter and bill, so an
 * auto-lock in the middle of taking an order doesn't lose it. */

export type DraftLine = {
  key: string;
  optionId: string;
  name: string; // display name, e.g. "Johnnie Walker Red - Single tot"
  price: number;
  quantity: number;
  note: string | null;
  station: "bar" | "kitchen";
};

const drafts = new Map<string, DraftLine[]>();

const id = (staffId: string, billId: string) => `${staffId}:${billId}`;

export function getDraft(staffId: string, billId: string): DraftLine[] {
  return drafts.get(id(staffId, billId)) ?? [];
}

export function saveDraft(staffId: string, billId: string, lines: DraftLine[]) {
  if (lines.length) drafts.set(id(staffId, billId), lines);
  else drafts.delete(id(staffId, billId));
}

/** Add one of an option; the same option with no note just goes up by one. */
export function addToDraft(lines: DraftLine[], line: Omit<DraftLine, "key" | "quantity">): DraftLine[] {
  const same = lines.find((l) => l.optionId === line.optionId && l.note === null);
  if (same) return lines.map((l) => (l === same ? { ...l, quantity: l.quantity + 1 } : l));
  return [...lines, { ...line, key: `${line.optionId}-${Date.now()}-${Math.random()}`, quantity: 1 }];
}

export function draftTotal(lines: DraftLine[]): number {
  return lines.reduce((sum, l) => sum + l.price * l.quantity, 0);
}
