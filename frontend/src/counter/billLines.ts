import type { BillLine } from "../services/api";

export function displayName(item: string, option: string) {
  return option ? `${item} - ${option}` : item;
}

export type LineGroup = {
  key: string;
  name: string;
  note: string | null;
  unitPrice: number;
  lines: BillLine[]; // the live (not voided) units
  voided: number;
};

/** Sent lines shown as "2× Tusker", one group per item, option, price and note. */
export function groupLines(lines: BillLine[]): LineGroup[] {
  const groups = new Map<string, LineGroup>();
  for (const line of lines) {
    const key = [line.item_name, line.option_label, line.unit_price, line.note ?? ""].join("|");
    let group = groups.get(key);
    if (!group) {
      group = { key, name: displayName(line.item_name, line.option_label), note: line.note, unitPrice: line.unit_price, lines: [], voided: 0 };
      groups.set(key, group);
    }
    if (line.voided) group.voided += 1;
    else group.lines.push(line);
  }
  return [...groups.values()];
}
