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
  modifiers: string[]; // "Coke +100"
  free: string | null; // why it was given free
  offer: string | null; // "Happy hour (was 300)"
  parts: string[]; // a combo's parts
};

export const COMP_LABEL: Record<string, string> = {
  house: "On the house",
  staff_drink: "Staff drink",
  owner_guest: "Owner's guest",
  complaint: "Complaint",
  promotion: "Promotion",
};

/** Sent lines shown as "2× Tusker": one group per item, option, price, note, choices and
 * free/offer status. A combo's parts are listed under the combo, not as their own lines. */
export function groupLines(lines: BillLine[]): LineGroup[] {
  const partsOf = new Map<string, string[]>();
  for (const l of lines) {
    if (l.combo_parent_id) partsOf.set(l.combo_parent_id, [...(partsOf.get(l.combo_parent_id) ?? []), displayName(l.item_name, l.option_label)]);
  }
  const groups = new Map<string, LineGroup>();
  for (const line of lines) {
    if (line.combo_parent_id) continue;
    const modifiers = line.modifiers.map((m) => (m.price ? `${m.label} +${m.price}` : m.label));
    const parts = partsOf.get(line.id) ?? [];
    const key = [line.item_name, line.option_label, line.unit_price, line.note ?? "", modifiers.join(","), line.comp_reason ?? ""].join("|");
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        name: displayName(line.item_name, line.option_label),
        note: line.note,
        unitPrice: line.unit_price,
        lines: [],
        voided: 0,
        modifiers,
        free: line.comp_reason ? COMP_LABEL[line.comp_reason] : null,
        offer: line.price_rule && line.list_price ? `${line.price_rule} (was ${line.list_price.toLocaleString("en-KE")})` : null,
        parts,
      };
      groups.set(key, group);
    }
    if (line.voided) group.voided += 1;
    else group.lines.push(line);
  }
  return [...groups.values()];
}
