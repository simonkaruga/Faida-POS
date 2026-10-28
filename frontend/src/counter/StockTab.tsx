import { useEffect, useMemo, useState } from "react";
import {
  addSupplier,
  ApiError,
  createStockItem,
  getManageMenu,
  getMovements,
  getRecipes,
  getStock,
  getSuppliers,
  receiveDelivery,
  recordWaste,
  setRecipe,
  stockTake,
  updateOption,
  updateStockItem,
  type Recipe,
  type RecipeLine,
  type Session,
  type StockItem,
  type StockMovement,
  type Supplier,
  type Variance,
} from "../services/api";
import { Keypad } from "../shared/Keypad";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");
const num = (s: string) => (s ? Number(s) : 0);
const plural = (unit: string) => (unit === "bottle" ? "bottles" : unit === "piece" ? "pcs" : unit === "kg" ? "kg" : `${unit}s`);
const KIND = { sale: "Sold", sale_return: "Back to stock", waste: "Waste", delivery: "Delivery", stock_take: "Stock take" } as Record<string, string>;
const STOCK_UNIT = { ml: "ml", g: "g", bottle: "bottles", piece: "pcs" } as const;

type View = "list" | "take" | "recipes";

/** Stock (masterplan 4.7-4.8): levels, deliveries, stock takes, waste; recipes and new
 * items for the owner. Buying prices and values are shown to the owner only. */
export function StockTab({ session }: { session: Session }) {
  const isOwner = session.permissions.manage_business === "allow";
  const [items, setItems] = useState<StockItem[] | null>(null);
  const [view, setView] = useState<View>("list");
  const [dialog, setDialog] = useState<null | "delivery" | "waste" | "new">(null);
  const [open, setOpen] = useState<StockItem | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => getStock().then(setItems, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);

  if (!items) return <p className="muted">{error ?? "Loading…"}</p>;
  if (view === "take") return <StockTakeView items={items} onDone={() => (setView("list"), load())} />;
  if (view === "recipes") return <RecipesView items={items} onBack={() => setView("list")} />;

  const total = items.reduce((s, i) => s + (i.value ?? 0), 0);
  const flagged = items.filter((i) => i.low || i.check).length;
  return (
    <>
      <div className="row" style={{ marginBottom: 12, flexWrap: "wrap" }}>
        <div className="grow">
          <h2 className="section-title" style={{ margin: 0 }}>
            Stock {flagged > 0 && <span className="warn">· {flagged} need attention</span>}
          </h2>
          {isOwner && <div className="muted">Stock value at buying price: {formatKsh(total)}</div>}
        </div>
        <button className="btn btn-primary" onClick={() => setDialog("delivery")}>
          DELIVERY
        </button>
        <button className="btn" onClick={() => setView("take")}>
          STOCK TAKE
        </button>
        <button className="btn btn-quiet" onClick={() => setDialog("waste")}>
          Waste
        </button>
        {isOwner && (
          <>
            <button className="btn btn-quiet" onClick={() => setView("recipes")}>
              Recipes
            </button>
            <button className="btn btn-quiet" onClick={() => setDialog("new")}>
              New item
            </button>
          </>
        )}
      </div>
      {message && <p className="ok-text">{message}</p>}
      {(["bar", "kitchen"] as const).map((station) => (
        <section key={station}>
          <h3 className="section-title">{station === "bar" ? "Bar" : "Kitchen"}</h3>
          <div className="list-table">
            {items
              .filter((i) => i.station === station && i.active)
              .map((i) => (
                <button key={i.id} className="list-row" onClick={() => setOpen(i)}>
                  <span className="grow">{i.name}</span>
                  {i.check && <span className="status-tag cancelled">CHECK: below zero</span>}
                  {!i.check && i.low && <span className="status-tag unpaid_responsible">LOW</span>}
                  {i.selling.length > 0 && (
                    <span className="muted" style={{ textAlign: "right" }}>
                      sells {i.selling.map((s) => formatKsh(s.price)).join(" · ")}
                    </span>
                  )}
                  <span className="amount" style={{ minWidth: 220 }}>
                    {i.level_text}
                  </span>
                  {isOwner && <span className="muted" style={{ minWidth: 90, textAlign: "right" }}>{formatKsh(i.value ?? 0)}</span>}
                </button>
              ))}
          </div>
        </section>
      ))}
      <p className="error-text">{error ?? ""}</p>

      {dialog === "delivery" && (
        <DeliveryDialog items={items} onDone={(lines) => (setDialog(null), setMessage(`Delivery saved: ${lines.join(", ")}`), load())} onClose={() => setDialog(null)} />
      )}
      {dialog === "waste" && (
        <WasteDialog items={items} onDone={(t) => (setDialog(null), setMessage(t), load())} onClose={() => setDialog(null)} />
      )}
      {dialog === "new" && <NewItemDialog onDone={() => (setDialog(null), load())} onClose={() => setDialog(null)} />}
      {open && <ItemDialog item={open} isOwner={isOwner} onChanged={() => (setOpen(null), load())} onClose={() => setOpen(null)} />}
    </>
  );
}

function ItemPicker({ items, onPick }: { items: StockItem[]; onPick: (i: StockItem) => void }) {
  const [q, setQ] = useState("");
  const shown = items.filter((i) => i.active && i.name.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <>
      <input className="text-input" placeholder="🔍 Find item" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="choice-grid picker">
        {shown.map((i) => (
          <button key={i.id} className="choice" onClick={() => onPick(i)}>
            {i.name}
          </button>
        ))}
      </div>
    </>
  );
}

type DeliveryLine = { item: StockItem; packs: string; units: string; cost: string };

function DeliveryDialog({ items, onDone, onClose }: { items: StockItem[]; onDone: (lines: string[]) => void; onClose: () => void }) {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplier, setSupplier] = useState<string | null>(null);
  const [newSupplier, setNewSupplier] = useState("");
  const [lines, setLines] = useState<DeliveryLine[]>([]);
  const [picking, setPicking] = useState(true);
  const [field, setField] = useState<{ index: number; key: "packs" | "units" | "cost" } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getSuppliers().then(setSuppliers, () => {});
  }, []);

  const add = (item: StockItem) => {
    setLines([...lines, { item, packs: "", units: "", cost: "" }]);
    setField({ index: lines.length, key: item.pack_size ? "packs" : "units" });
    setPicking(false);
  };
  const setValue = (v: string) => field && setLines(lines.map((l, i) => (i === field.index ? { ...l, [field.key]: v } : l)));
  const save = async () => {
    try {
      let supplierId = supplier ?? undefined;
      if (!supplierId && newSupplier.trim()) supplierId = (await addSupplier(newSupplier.trim(), null)).id;
      const r = await receiveDelivery({
        supplier_id: supplierId,
        lines: lines.map((l) => ({ stock_item_id: l.item.id, packs: num(l.packs), units: num(l.units), cost: l.cost ? num(l.cost) : undefined })),
      });
      onDone(r.lines);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const cell = (index: number, key: "packs" | "units" | "cost", label: string, value: string) => (
    <button className={`field-box small ${field?.index === index && field.key === key ? "active" : ""}`} onClick={() => setField({ index, key })}>
      <span className="muted">{label}</span>
      <strong>{value || "—"}</strong>
    </button>
  );
  const current = field ? lines[field.index] : null;

  return (
    <Modal title="Delivery" onClose={onClose} wide>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <span className="muted">Supplier:</span>
        {suppliers.map((s) => (
          <button key={s.id} className={`btn ${supplier === s.id ? "btn-primary" : "btn-quiet"}`} onClick={() => setSupplier(supplier === s.id ? null : s.id)}>
            {s.name}
          </button>
        ))}
        {!supplier && <input className="text-input" placeholder="New supplier (optional)" value={newSupplier} onChange={(e) => setNewSupplier(e.target.value)} />}
      </div>
      {picking ? (
        <ItemPicker items={items} onPick={add} />
      ) : (
        <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
          <div className="choice-list grow">
            {lines.map((l, i) => (
              <div key={i} className="delivery-row">
                <strong className="grow">{l.item.name}</strong>
                {l.item.pack_size && cell(i, "packs", `${l.item.pack_name ?? "pack"}s of ${l.item.pack_size}`, l.packs)}
                {cell(i, "units", `loose ${plural(l.item.counting_unit)}`, l.units)}
                {cell(i, "cost", "cost (KSh)", l.cost ? formatKsh(num(l.cost)) : "")}
              </div>
            ))}
            <div className="row">
              <button className="btn btn-quiet" onClick={() => setPicking(true)}>
                + Add item
              </button>
              <span className="grow" />
              <button className="btn btn-primary" onClick={save} disabled={!lines.length}>
                SAVE DELIVERY
              </button>
            </div>
            <p className="error-text">{error ?? ""}</p>
          </div>
          {current && field && (
            <Keypad
              value={current[field.key]}
              onChange={(v) => setValue(v.replace(/^0+(?=\d)/, ""))}
              onEnter={() => setField(null)}
              decimal={field.key === "units" && current.item.counting_unit !== "bottle" && current.item.counting_unit !== "piece"}
              maxLength={9}
            />
          )}
        </div>
      )}
    </Modal>
  );
}

const WASTE_REASONS = ["Broken bottle", "Spilt", "Expired", "Spoilt food", "Dropped"];

function WasteDialog({ items, onDone, onClose }: { items: StockItem[]; onDone: (text: string) => void; onClose: () => void }) {
  const [item, setItem] = useState<StockItem | null>(null);
  const [byTot, setByTot] = useState(false);
  const [value, setValue] = useState("");
  const [reason, setReason] = useState(WASTE_REASONS[0]);
  const [error, setError] = useState<string | null>(null);
  if (!item) {
    return (
      <Modal title="Waste: which item?" onClose={onClose} wide>
        <ItemPicker items={items} onPick={(i) => (setItem(i), setByTot(i.bottle_size !== null))} />
      </Modal>
    );
  }
  const spirit = item.bottle_size !== null;
  const save = () =>
    recordWaste({ stock_item_id: item.id, quantity: byTot ? 0 : num(value), tots: byTot ? num(value) : 0, reason }).then(
      (r) => onDone(`Waste recorded: ${item.name}. Now ${r.level_text}.`),
      (e) => setError(errorText(e)),
    );
  return (
    <Modal title={`Waste: ${item.name}`} onClose={onClose} wide>
      <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
        <div className="choice-list grow">
          {spirit && (
            <div className="row">
              <button className={`btn grow ${byTot ? "btn-primary" : "btn-quiet"}`} onClick={() => setByTot(true)}>
                Tots
              </button>
              <button className={`btn grow ${!byTot ? "btn-primary" : "btn-quiet"}`} onClick={() => setByTot(false)}>
                Bottles
              </button>
            </div>
          )}
          <div className="field-box active">
            <span className="muted">{byTot ? "tots" : plural(item.counting_unit)}</span>
            <strong>{value || "—"}</strong>
          </div>
          <div className="choice-grid">
            {WASTE_REASONS.map((r) => (
              <button key={r} className={`choice ${reason === r ? "selected" : ""}`} onClick={() => setReason(r)}>
                {r}
              </button>
            ))}
          </div>
          <p className="error-text">{error ?? ""}</p>
          <button className="btn btn-primary" disabled={!num(value)} onClick={save}>
            RECORD WASTE
          </button>
        </div>
        <Keypad value={value} onChange={setValue} onEnter={save} decimal={!byTot && item.counting_unit !== "piece"} maxLength={7} />
      </div>
    </Modal>
  );
}

type Count = { full: string; tenths: number };

/** Count sealed bottles (or kg, pieces) and the open bottle in tenths. Faida doesn't show
 * what it expects until the count is saved, so the count isn't nudged. */
function StockTakeView({ items, onDone }: { items: StockItem[]; onDone: () => void }) {
  const [station, setStation] = useState<"bar" | "kitchen">("bar");
  const [counts, setCounts] = useState<Record<string, Count>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [result, setResult] = useState<{ lines: Variance[]; total: number | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const shown = useMemo(() => items.filter((i) => i.station === station && i.active), [items, station]);
  const counted = Object.keys(counts).length;
  const sel = items.find((i) => i.id === selected);
  const set = (id: string, c: Partial<Count>) => setCounts({ ...counts, [id]: { ...{ full: "", tenths: 0 }, ...counts[id], ...c } });

  const save = () =>
    stockTake(
      undefined,
      Object.entries(counts).map(([id, c]) => ({ stock_item_id: id, full: num(c.full), open_tenths: c.tenths })),
    ).then((r) => setResult({ lines: r.lines, total: r.total_value }), (e) => setError(errorText(e)));

  if (result) {
    return (
      <>
        <h2 className="section-title">Stock take: {result.lines.length} {result.lines.length === 1 ? "item" : "items"} counted</h2>
        {result.total !== null && (
          <p style={{ fontSize: 22, fontWeight: 700 }} className={result.total < 0 ? "warn" : ""}>
            Variance at buying price: {result.total < 0 ? "−" : ""}KSh {formatKsh(Math.abs(result.total))}
          </p>
        )}
        <div className="list-table">
          {result.lines.map((l) => (
            <div key={l.stock_item_id} className="shift-row">
              <strong className="grow">{l.name}</strong>
              <span className="muted">
                expected {l.expected_text} · counted {l.counted_text}
              </span>
              <span className={Number(l.variance) < 0 ? "warn" : Number(l.variance) > 0 ? "" : "muted"} style={{ minWidth: 300, textAlign: "right" }}>
                {l.message}
              </span>
            </div>
          ))}
        </div>
        <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={onDone}>
          DONE
        </button>
      </>
    );
  }

  return (
    <div className="take">
      <div className="take-list">
        <div className="row" style={{ marginBottom: 8 }}>
          {(["bar", "kitchen"] as const).map((s) => (
            <button key={s} className={`cat ${station === s ? "selected" : ""}`} onClick={() => setStation(s)}>
              {s === "bar" ? "Bar" : "Kitchen"}
            </button>
          ))}
          <span className="grow muted">{counted} counted</span>
          <button className="btn btn-quiet" onClick={onDone}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={!counted} onClick={save}>
            SAVE COUNT
          </button>
        </div>
        <p className="error-text">{error ?? ""}</p>
        {shown.map((i) => {
          const c = counts[i.id];
          return (
            <div key={i.id} className={`take-row ${selected === i.id ? "active" : ""} ${c ? "done" : ""}`}>
              <button className="take-name" onClick={() => setSelected(i.id)}>
                <span>{i.name}</span>
                <strong>
                  {c ? `${c.full || 0} ${plural(i.counting_unit)}` : "—"}
                  {c && i.bottle_size ? ` + ${c.tenths}/10` : ""}
                </strong>
              </button>
              {i.bottle_size !== null && (
                <label className="tenths">
                  <span className="muted">open bottle</span>
                  <input type="range" min={0} max={9} step={1} value={c?.tenths ?? 0} onChange={(e) => set(i.id, { tenths: Number(e.target.value) })} />
                  <strong>{c?.tenths ?? 0}/10</strong>
                </label>
              )}
            </div>
          );
        })}
      </div>
      <div className="pay-pad">
        {sel ? (
          <>
            <p style={{ fontSize: 20, margin: 0, textAlign: "center" }}>
              <strong>{sel.name}</strong>
              <br />
              <span className="muted">{sel.bottle_size ? "sealed bottles" : plural(sel.counting_unit)}</span>
            </p>
            <Keypad
              value={counts[sel.id]?.full ?? ""}
              onChange={(v) => set(sel.id, { full: v })}
              onEnter={() => {
                if (!counts[sel.id]) set(sel.id, { full: "0" });
                const next = shown[shown.findIndex((i) => i.id === sel.id) + 1];
                setSelected(next?.id ?? null);
              }}
              decimal={sel.counting_unit === "kg" || sel.counting_unit === "litre"}
              enterLabel="NEXT"
              allowEmptyEnter
              maxLength={7}
            />
          </>
        ) : (
          <p className="muted">Tap an item to count it.</p>
        )}
      </div>
    </div>
  );
}

function ItemDialog({ item, isOwner, onChanged, onClose }: { item: StockItem; isOwner: boolean; onChanged: () => void; onClose: () => void }) {
  const [moves, setMoves] = useState<StockMovement[] | null>(null);
  const [price, setPrice] = useState(item.buying_price ?? "");
  const [reorder, setReorder] = useState(String(Number(item.reorder_level) / (item.bottle_size ?? (item.unit === "ml" || item.unit === "g" ? 1000 : 1))));
  const [selling, setSelling] = useState(item.selling.map((s) => ({ ...s, price: String(s.price) })));
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    try {
      await updateStockItem(item.id, { buying_price: price || undefined, reorder_level: reorder || undefined });
      for (const s of selling) {
        const before = item.selling.find((b) => b.option_id === s.option_id);
        if (s.price !== "" && Number(s.price) !== before?.price) await updateOption(s.option_id, { price: Number(s.price) });
      }
      onChanged();
    } catch (e) {
      setError(errorText(e));
    }
  };
  useEffect(() => {
    getMovements(item.id).then(setMoves, (e) => setError(errorText(e)));
  }, [item.id]);
  return (
    <Modal title={`${item.name}: ${item.level_text}`} onClose={onClose} wide>
      {isOwner && (
        <div className="row" style={{ flexWrap: "wrap" }}>
          <label className="row">
            <span className="muted">Buying price per {item.counting_unit}</span>
            <input className="text-input" style={{ width: 130 }} inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
          </label>
          <label className="row">
            <span className="muted">Reorder at ({plural(item.counting_unit)})</span>
            <input className="text-input" style={{ width: 100 }} inputMode="decimal" value={reorder} onChange={(e) => setReorder(e.target.value)} />
          </label>
          <button className="btn btn-primary" onClick={save}>
            SAVE
          </button>
        </div>
      )}
      {isOwner && selling.length > 0 && (
        <div className="row" style={{ flexWrap: "wrap" }}>
          {selling.map((s, i) => (
            <label key={s.option_id} className="row">
              <span className="muted">Selling price: {s.name}</span>
              <input
                className="text-input"
                style={{ width: 110 }}
                inputMode="numeric"
                value={s.price}
                onChange={(e) => setSelling(selling.map((x, j) => (j === i ? { ...x, price: e.target.value.replace(/\D/g, "") } : x)))}
              />
            </label>
          ))}
        </div>
      )}
      {isOwner && !selling.length && <p className="muted">Not sold on the menu. Link it under Recipes, or add it from New item.</p>}
      <p className="error-text">{error ?? ""}</p>
      <div className="list-table movements">
        {moves?.map((m, i) => (
          <div key={i} className="row" style={{ fontSize: 17 }}>
            <span className="muted" style={{ minWidth: 120 }}>
              {new Date(m.at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
            </span>
            <span style={{ minWidth: 120 }}>{KIND[m.kind] ?? m.kind}</span>
            <span className="grow muted">
              {m.note} {m.by ? `· ${m.by}` : ""}
            </span>
            <span className={Number(m.quantity) < 0 ? "warn" : ""}>
              {Number(m.quantity) > 0 ? "+" : "−"}
              {m.text.replace(/^-/, "")}
            </span>
          </div>
        ))}
        {moves?.length === 0 && <p className="muted">No movements yet.</p>}
      </div>
    </Modal>
  );
}

function NewItemDialog({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const [form, setForm] = useState({ name: "", station: "bar", unit: "bottle", bottle_size: "", pack_name: "", pack_size: "", buying_price: "", reorder_level: "", price: "", tot_price: "" });
  const [categories, setCategories] = useState<{ id: string; name: string }[]>([]);
  const [category, setCategory] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getManageMenu().then((m) => setCategories(m.categories.filter((c) => c.active)), () => {});
  }, []);
  const set = (k: keyof typeof form, v: string) => setForm({ ...form, [k]: v });
  const counting = form.unit === "ml" ? (form.bottle_size ? "bottle" : "litre") : form.unit === "g" ? "kg" : form.unit;
  const spirit = form.unit === "ml" && !!form.bottle_size;
  const tot = spirit && form.tot_price;
  const save = () => {
    if (category && !form.price && !tot) return setError("Type the selling price, or choose Not sold.");
    if (!category && (form.price || tot)) return setError("Choose the menu category it sells under.");
    return createStockItem({
      name: form.name.trim(),
      station: form.station,
      unit: form.unit,
      bottle_size: form.unit === "ml" && form.bottle_size ? num(form.bottle_size) : null,
      pack_name: form.pack_name.trim() || null,
      pack_size: form.pack_size ? num(form.pack_size) : null,
      buying_price: form.buying_price || null,
      reorder_level: form.reorder_level || 0,
      sell: category ? { category_id: category, price: form.price ? num(form.price) : null, tot_price: tot ? num(form.tot_price) : null } : null,
    }).then(onDone, (e) => setError(errorText(e)));
  };
  const text = (k: keyof typeof form, placeholder: string, mode: "text" | "decimal" = "text") => (
    <input className="text-input" placeholder={placeholder} inputMode={mode} value={form[k]} onChange={(e) => set(k, e.target.value)} />
  );
  return (
    <Modal title="New stock item" onClose={onClose} wide>
      {text("name", "Name, e.g. Captain Morgan 250ml")}
      <div className="row">
        {(["bar", "kitchen"] as const).map((s) => (
          <button key={s} className={`btn grow ${form.station === s ? "btn-primary" : "btn-quiet"}`} onClick={() => set("station", s)}>
            {s === "bar" ? "Bar" : "Kitchen"}
          </button>
        ))}
      </div>
      <div className="row">
        {(["bottle", "ml", "g", "piece"] as const).map((u) => (
          <button key={u} className={`btn grow ${form.unit === u ? "btn-primary" : "btn-quiet"}`} onClick={() => set("unit", u)}>
            {{ bottle: "Bottles (beer, soda)", ml: "ml (spirits, oil)", g: "Grams", piece: "Pieces" }[u]}
          </button>
        ))}
      </div>
      {form.unit === "ml" && text("bottle_size", "Bottle size in ml, e.g. 750 (spirits)", "decimal")}
      <div className="row">
        {text("pack_name", "Pack name, e.g. crate")}
        {text("pack_size", `${plural(counting)} per pack`, "decimal")}
      </div>
      <div className="row">
        {text("buying_price", `Buying price per ${counting}`, "decimal")}
        {text("reorder_level", `Reorder at (${plural(counting)})`, "decimal")}
      </div>
      <h3 className="form-title">Sell it on the menu</h3>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <button className={`btn ${category === null ? "btn-primary" : "btn-quiet"}`} onClick={() => setCategory(null)}>
          Not sold (ingredient)
        </button>
        {categories.map((c) => (
          <button key={c.id} className={`btn ${category === c.id ? "btn-primary" : "btn-quiet"}`} onClick={() => setCategory(c.id)}>
            {c.name}
          </button>
        ))}
      </div>
      {category && (
        <div className="row">
          {text("price", `Selling price per ${counting} (KSh)`, "decimal")}
          {spirit && text("tot_price", "Selling price per tot (KSh)", "decimal")}
        </div>
      )}
      <p className="error-text">{error ?? ""}</p>
      <div className="row row-end">
        <button className="btn btn-primary" disabled={!form.name.trim()} onClick={save}>
          ADD ITEM
        </button>
      </div>
    </Modal>
  );
}

/** What each menu option takes out of stock. Quantities are in the stock item's own
 * unit (ml, g, bottles, pieces), or tots for a spirit. */
function RecipesView({ items, onBack }: { items: StockItem[]; onBack: () => void }) {
  const [recipes, setRecipes] = useState<Recipe[] | null>(null);
  const [editing, setEditing] = useState<Recipe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => getRecipes().then(setRecipes, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);
  if (!recipes) return <p className="muted">{error ?? "Loading…"}</p>;
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className="btn btn-quiet" onClick={onBack}>
          ‹ Stock
        </button>
        <h2 className="section-title grow" style={{ margin: 0 }}>
          Recipes: what each sale takes from stock
        </h2>
      </div>
      <div className="list-table">
        {recipes.map((r) => (
          <button key={r.sell_option_id} className="list-row" onClick={() => setEditing(r)}>
            <span style={{ minWidth: 320 }}>
              <strong>{r.item_name}</strong> {r.option_label && <span className="muted">· {r.option_label}</span>}
            </span>
            <span className={`grow ${r.lines.length ? "" : "warn"}`}>
              {r.lines.length ? r.lines.map((l) => `${l.text} ${l.stock_item}`).join(" + ") : "Not tracked"}
            </span>
          </button>
        ))}
      </div>
      {editing && <RecipeDialog recipe={editing} items={items} onDone={() => (setEditing(null), load())} onClose={() => setEditing(null)} />}
    </>
  );
}

function RecipeDialog({ recipe, items, onDone, onClose }: { recipe: Recipe; items: StockItem[]; onDone: () => void; onClose: () => void }) {
  const [lines, setLines] = useState<RecipeLine[]>(recipe.lines.map(({ stock_item_id, quantity, in_tots }) => ({ stock_item_id, quantity: String(Number(quantity)), in_tots })));
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const byId = Object.fromEntries(items.map((i) => [i.id, i]));
  const update = (i: number, patch: Partial<RecipeLine>) => setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const save = () => setRecipe(recipe.sell_option_id, lines.filter((l) => Number(l.quantity) > 0)).then(onDone, (e) => setError(errorText(e)));
  return (
    <Modal title={`${recipe.item_name}${recipe.option_label ? ` · ${recipe.option_label}` : ""}`} onClose={onClose} wide>
      {picking ? (
        <ItemPicker
          items={items}
          onPick={(i) => (setLines([...lines, { stock_item_id: i.id, quantity: i.bottle_size ? "1" : "1", in_tots: i.bottle_size !== null }]), setPicking(false))}
        />
      ) : (
        <>
          {lines.map((l, i) => {
            const s = byId[l.stock_item_id];
            return (
              <div key={i} className="row">
                <strong className="grow">{s?.name}</strong>
                <input className="text-input" style={{ width: 110 }} inputMode="decimal" value={l.quantity} onChange={(e) => update(i, { quantity: e.target.value })} />
                {s?.unit === "ml" && s.bottle_size ? (
                  <button className="btn btn-quiet" onClick={() => update(i, { in_tots: !l.in_tots })}>
                    {l.in_tots ? "tots" : "ml"}
                  </button>
                ) : (
                  <span className="muted" style={{ minWidth: 70 }}>
                    {s ? STOCK_UNIT[s.unit] : ""}
                  </span>
                )}
                <button className="btn btn-quiet" onClick={() => setLines(lines.filter((_, j) => j !== i))} aria-label="Remove">
                  ✕
                </button>
              </div>
            );
          })}
          {!lines.length && <p className="muted">Nothing: sales of this aren't taken from stock.</p>}
          <p className="error-text">{error ?? ""}</p>
          <div className="row">
            <button className="btn btn-quiet" onClick={() => setPicking(true)}>
              + Add stock item
            </button>
            <span className="grow" />
            <button className="btn btn-primary" onClick={save}>
              SAVE RECIPE
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
