import { Check, Minus, Plus } from "lucide-react";
import { useState } from "react";
import type { MenuItem } from "../services/api";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";
import type { DraftModifier } from "./drafts";

export type ItemChoice = { optionIndex: number; modifiers: DraftModifier[]; quantity: number };

/** Choosing how an item is sold: the size (single tot, double, bottle) and its
 * modifiers (mixer, side, how cooked). Required choices are marked; ADD stays off
 * until they're made. */
export function ItemDialog({ item, onAdd, onClose }: { item: MenuItem; onAdd: (choice: ItemChoice) => void; onClose: () => void }) {
  const [optionIndex, setOptionIndex] = useState(item.options.length === 1 ? 0 : -1);
  const [picked, setPicked] = useState<Record<string, string[]>>({});
  const [quantity, setQuantity] = useState(1);

  const toggle = (groupId: string, optionId: string, max: number) => {
    const now = picked[groupId] ?? [];
    const next = now.includes(optionId)
      ? now.filter((x) => x !== optionId)
      : max === 1
        ? [optionId]
        : now.length < max
          ? [...now, optionId]
          : now;
    setPicked({ ...picked, [groupId]: next });
  };
  const missing = item.modifier_groups.filter((g) => (picked[g.id]?.length ?? 0) < g.min_select);
  const modifiers: DraftModifier[] = item.modifier_groups.flatMap((g) =>
    g.options.filter((o) => picked[g.id]?.includes(o.id)).map((o) => ({ id: o.id, label: o.label, price: o.price })),
  );
  const option = item.options[optionIndex];
  const unit = option ? (option.offer_price ?? option.price) + modifiers.reduce((s, m) => s + m.price, 0) : 0;
  const ready = optionIndex >= 0 && missing.length === 0;

  return (
    <Modal title={item.name} onClose={onClose} wide={item.modifier_groups.length > 0}>
      {item.options.length > 1 && (
        <section className="pick-group">
          <h3>
            Size <span className="pill orange">required</span>
          </h3>
          <div className="choice-grid">
            {item.options.map((o, i) => (
              <button key={o.id} className={`choice ${optionIndex === i ? "selected" : ""}`} onClick={() => setOptionIndex(i)}>
                <span>{o.label}</span>
                <PriceTag price={o.price} offer={o.offer_price} />
              </button>
            ))}
          </div>
        </section>
      )}
      {item.modifier_groups.map((g) => (
        <section key={g.id} className="pick-group">
          <h3>
            {g.name}{" "}
            {g.min_select > 0 ? (
              <span className={`pill ${(picked[g.id]?.length ?? 0) >= g.min_select ? "green" : "orange"}`}>required</span>
            ) : (
              <span className="pill">optional</span>
            )}
            {g.max_select > 1 && <span className="muted"> · up to {g.max_select}</span>}
          </h3>
          <div className="choice-grid">
            {g.options.map((o) => {
              const on = picked[g.id]?.includes(o.id);
              return (
                <button key={o.id} className={`choice ${on ? "selected" : ""}`} onClick={() => toggle(g.id, o.id, g.max_select)}>
                  <span className="row" style={{ gap: 8 }}>
                    {on && <Check size={18} />}
                    {o.label}
                  </span>
                  {o.price > 0 && <small>+{formatKsh(o.price)}</small>}
                </button>
              );
            })}
          </div>
        </section>
      ))}
      <div className="row" style={{ marginTop: 6 }}>
        <button className="step" onClick={() => setQuantity(Math.max(1, quantity - 1))} aria-label="One less">
          <Minus size={18} />
        </button>
        <strong style={{ fontSize: 24, minWidth: 36, textAlign: "center" }}>{quantity}</strong>
        <button className="step" onClick={() => setQuantity(quantity + 1)} aria-label="One more">
          <Plus size={18} />
        </button>
        <span className="grow muted">{missing.length ? `Choose ${missing.map((g) => g.name.toLowerCase()).join(" and ")}` : ""}</span>
        <button className="btn btn-primary" disabled={!ready} onClick={() => onAdd({ optionIndex, modifiers, quantity })}>
          <Plus size={22} /> ADD {ready ? formatKsh(unit * quantity) : ""}
        </button>
      </div>
    </Modal>
  );
}

/** A price, with the usual price struck through while a happy hour is on. */
export function PriceTag({ price, offer }: { price: number; offer: number | null }) {
  if (offer === null || offer === price) return <span className="price-tag">{formatKsh(price)}</span>;
  return (
    <span className="price-tag offer">
      <s>{formatKsh(price)}</s> {formatKsh(offer)}
    </span>
  );
}
