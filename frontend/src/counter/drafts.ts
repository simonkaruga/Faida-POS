/** The round being built, before SEND. Kept in memory per waiter and bill, so an
 * auto-lock in the middle of taking an order doesn't lose it. */

export type DraftModifier = { id: string; label: string; price: number };

export type DraftLine = {
  key: string;
  optionId: string;
  name: string; // display name, e.g. "Johnnie Walker Red - Single tot"
  price: number; // per unit, with any happy hour and modifiers
  quantity: number;
  note: string | null;
  station: "bar" | "kitchen";
  modifiers: DraftModifier[];
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

const sameChoices = (a: DraftModifier[], b: DraftModifier[]) =>
  a.length === b.length && a.every((m) => b.some((n) => n.id === m.id));

/** Add some of an option; the same option with the same choices and no note just goes up. */
export function addToDraft(
  lines: DraftLine[],
  line: Omit<DraftLine, "key" | "quantity" | "modifiers"> & { modifiers?: DraftModifier[]; quantity?: number },
): DraftLine[] {
  const modifiers = line.modifiers ?? [];
  const quantity = line.quantity ?? 1;
  const same = lines.find((l) => l.optionId === line.optionId && l.note === line.note && sameChoices(l.modifiers, modifiers));
  if (same) return lines.map((l) => (l === same ? { ...l, quantity: l.quantity + quantity } : l));
  return [...lines, { ...line, modifiers, quantity, key: `${line.optionId}-${Date.now()}-${Math.random()}` }];
}

export function draftTotal(lines: DraftLine[]): number {
  return lines.reduce((sum, l) => sum + l.price * l.quantity, 0);
}
