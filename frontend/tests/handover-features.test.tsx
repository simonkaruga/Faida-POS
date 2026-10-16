import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { addToDraft, type DraftLine } from "../src/counter/drafts";
import { ItemDialog } from "../src/counter/ItemDialog";
import type { MenuItem } from "../src/services/api";

afterEach(cleanup);

const whisky: MenuItem = {
  id: "w",
  name: "Jameson",
  station: "bar",
  favourite: false,
  available: true,
  image: null,
  is_combo: false,
  combo_parts: [],
  options: [
    { id: "single", label: "Single tot", price: 250, offer_price: 200, offer: "Happy hour" },
    { id: "double", label: "Double tot", price: 450, offer_price: null, offer: null },
  ],
  modifier_groups: [
    { id: "mixer", name: "Mixer", min_select: 1, max_select: 1, options: [{ id: "coke", label: "Coke", price: 100 }, { id: "water", label: "Water", price: 0 }] },
  ],
};

describe("choosing an item", () => {
  it("asks for the size and the required mixer, and uses the happy hour price", () => {
    const onAdd = vi.fn();
    render(<ItemDialog item={whisky} onAdd={onAdd} onClose={vi.fn()} />);
    const add = () => screen.getAllByRole("button").find((b) => /^ADD/.test((b.textContent ?? "").trim()))!;
    expect((add() as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByText("Single tot"));
    expect((add() as HTMLButtonElement).disabled).toBe(true); // the mixer is still missing
    fireEvent.click(screen.getByText("Coke"));
    expect((add() as HTMLButtonElement).disabled).toBe(false);
    expect(add().textContent).toContain("300"); // 200 offer + 100 Coke
    fireEvent.click(add());
    expect(onAdd).toHaveBeenCalledWith({ optionIndex: 0, modifiers: [{ id: "coke", label: "Coke", price: 100 }], quantity: 1 });
  });
});

describe("the order being built", () => {
  const line = (modifiers: DraftLine["modifiers"], quantity?: number) => ({
    optionId: "single", name: "Jameson - Single tot", price: 300, note: null, station: "bar" as const, modifiers, quantity,
  });

  it("keeps different mixers apart and adds up the same ones", () => {
    let draft: DraftLine[] = [];
    draft = addToDraft(draft, line([{ id: "coke", label: "Coke", price: 100 }]));
    draft = addToDraft(draft, line([{ id: "coke", label: "Coke", price: 100 }]));
    draft = addToDraft(draft, line([{ id: "water", label: "Water", price: 0 }], 2));
    expect(draft.map((d) => [d.modifiers.map((m) => m.label).join(), d.quantity])).toEqual([
      ["Coke", 2],
      ["Water", 2],
    ]);
  });
});
