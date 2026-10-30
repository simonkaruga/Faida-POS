import { useEffect, useMemo, useState } from "react";
import {
  addSupplier,
  ApiError,
  createStockItem,
  getActiveStaff,
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
  type TakeKind,
  type Supplier,
  type Variance,
} from "../services/api";
import { Pencil } from "lucide-react";
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
  const [dialog, setDialog] = useState<null | "delivery" | "waste" | "new" | "clear">(null);
  const [open, setOpen] = useState<StockItem | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => getStock().then(setItems, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);

  if (!items) return <p className="muted">{error ?? "Loading…"}</p>;
  if (view === "take") return <StockTakeView items={items} isOwner={isOwner} onReload={load} onDone={() => (setView("list"), load())} />;
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
            <button className="btn btn-quiet" onClick={() => setDialog("clear")}>
              Clear all to 0
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
      {dialog === "clear" && (
        <Modal title="Clear all stock to 0?" onClose={() => setDialog(null)}>
          <p style={{ margin: 0, fontSize: 18 }}>
            Every item's stock becomes 0, to start counting afresh. The items, prices and recipes stay, and so do the sales. Then put the stock in again
            with DELIVERY or a STOCK TAKE. This is recorded as a stock count, so it shows in each item's history.
          </p>
          <div className="row row-end">
            <button className="btn btn-quiet" onClick={() => setDialog(null)}>
              Keep the stock
            </button>
            <button
              className="btn btn-red"
              onClick={() =>
                stockTake(
                  "Cleared to 0 to start afresh",
                  items.filter((i) => i.active).map((i) => ({ stock_item_id: i.id, full: 0, open_tenths: 0 })),
                ).then(
                  () => (setDialog(null), setMessage("All stock is 0 now. Put it in with DELIVERY or STOCK TAKE."), load()),
                  (e) => (setDialog(null), setError(errorText(e))),
                )
              }
            >
              CLEAR ALL TO 0
            </button>
          </div>
        </Modal>
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
type DeliveryKey = "packs" | "units" | "cost";

/** Counting units per stock unit: a bottle of a spirit in ml, a litre, a kg. */
const per = (i: StockItem) => i.bottle_size ?? (i.unit === "ml" || i.unit === "g" ? 1000 : 1);
const round = (n: number) => Math.round(n * 10) / 10;

/** Stock in, item by item: whole crates (or cartons) and single bottles that came without
 * a crate, in any mix, and what was paid. Each line shows what it adds up to and the stock
 * after, so 5 in stock + 2 crates + 2 bottles = 55 is visible before saving. */
function DeliveryDialog({ items, onDone, onClose }: { items: StockItem[]; onDone: (lines: string[]) => void; onClose: () => void }) {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplier, setSupplier] = useState<string | null>(null);
  const [newSupplier, setNewSupplier] = useState("");
  const [lines, setLines] = useState<DeliveryLine[]>([]);
  const [picking, setPicking] = useState(true);
  const [field, setField] = useState<{ index: number; key: DeliveryKey } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getSuppliers().then(setSuppliers, () => {});
  }, []);

  const add = (item: StockItem) => {
    const at = lines.findIndex((l) => l.item.id === item.id);
    if (at < 0) setLines([...lines, { item, packs: "", units: "", cost: "" }]);
    setField({ index: at < 0 ? lines.length : at, key: item.pack_size ? "packs" : "units" });
    setPicking(false);
  };
  const drop = (index: number) => (setLines(lines.filter((_, i) => i !== index)), setField(null));
  const setValue = (v: string) => field && setLines(lines.map((l, i) => (i === field.index ? { ...l, [field.key]: v } : l)));
  const total = (l: DeliveryLine) => num(l.packs) * (l.item.pack_size ?? 0) + num(l.units);
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

  const unitName = (i: StockItem) => (i.counting_unit === "bottle" ? "single bottles" : plural(i.counting_unit));
  const label = (l: DeliveryLine, key: DeliveryKey) =>
    key === "packs" ? `${l.item.pack_name ?? "Crate"}s (${l.item.pack_size} each)` : key === "units" ? (l.item.pack_size ? `${unitName(l.item)} (no ${(l.item.pack_name ?? "crate").toLowerCase()})` : unitName(l.item)) : "Total paid, KSh (optional)";
  const cell = (index: number, key: DeliveryKey) => {
    const l = lines[index];
    const value = key === "cost" ? (l.cost ? formatKsh(num(l.cost)) : "") : l[key];
    return (
      <button className={`field-box small ${field?.index === index && field.key === key ? "active" : ""}`} style={{ flex: 1 }} onClick={() => setField({ index, key })}>
        <span className="muted">{label(l, key)}</span>
        <strong>{value || "—"}</strong>
      </button>
    );
  };
  const current = field ? lines[field.index] : null;
  const ready = lines.length > 0 && lines.every((l) => total(l) > 0);

  return (
    <Modal title="Delivery: stock that came in" onClose={onClose} wide>
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
        <>
          <p className="muted" style={{ margin: 0 }}>
            Tap what came in. {lines.length > 0 && <button className="btn btn-quiet" onClick={() => setPicking(false)}>‹ Back to the delivery</button>}
          </p>
          <ItemPicker items={items} onPick={add} />
        </>
      ) : (
        <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
          <div className="choice-list grow">
            {lines.map((l, i) => {
              const now = Number(l.item.level) / per(l.item);
              const came = total(l);
              const unit = plural(l.item.counting_unit);
              return (
                <div key={l.item.id} className="delivery-card">
                  <div className="row">
                    <strong className="grow" style={{ fontSize: 20 }}>
                      {l.item.name}
                    </strong>
                    <button className="btn btn-quiet" onClick={() => drop(i)} aria-label={`Take ${l.item.name} off`}>
                      ✕
                    </button>
                  </div>
                  <div className="row" style={{ flexWrap: "wrap" }}>
                    {l.item.pack_size && cell(i, "packs")}
                    {cell(i, "units")}
                    {cell(i, "cost")}
                  </div>
                  <div className={came ? "" : "muted"}>
                    {came
                      ? `Came in: ${round(came)} ${unit}${l.cost && came ? ` (KSh ${formatKsh(num(l.cost) / came)} each)` : ""} · in stock now ${round(now)} → after ${round(now + came)} ${unit}`
                      : `In stock now: ${l.item.level_text}. Type how many came in.`}
                  </div>
                </div>
              );
            })}
            <div className="row">
              <button className="btn btn-quiet" onClick={() => setPicking(true)}>
                + Add another item
              </button>
              <span className="grow" />
              <button className="btn btn-primary" onClick={save} disabled={!ready}>
                SAVE DELIVERY
              </button>
            </div>
            <p className="error-text">{error ?? ""}</p>
          </div>
          {current && field && (
            <div>
              <p style={{ fontSize: 18, margin: "0 0 8px", textAlign: "center", maxWidth: 300 }}>
                {current.item.name}:<br />
                <strong>{label(current, field.key)}</strong>
              </p>
              <Keypad
                value={current[field.key]}
                onChange={(v) => setValue(v.replace(/^0+(?=\d)/, ""))}
                onEnter={() => setField(field.key === "packs" ? { index: field.index, key: "units" } : null)}
                decimal={field.key === "units" && current.item.counting_unit !== "bottle" && current.item.counting_unit !== "piece"}
                maxLength={9}
              />
            </div>
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

/** The stock sheet of a count: opening (the last count) + received − sold − waste =
 * expected, against what was counted. */
export function StockSheet({ lines }: { lines: Variance[] }) {
  return (
    <div className="stock-sheet">
      <table>
        <thead>
          <tr>
            <th>Item</th>
            <th>Opening</th>
            <th>+ Received</th>
            <th>− Sold</th>
            <th>− Waste</th>
            <th>= Expected</th>
            <th>Counted</th>
            <th>Difference</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.stock_item_id}>
              <td>
                <strong>{l.name}</strong>
                {l.since && <div className="muted">since {new Date(l.since).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</div>}
              </td>
              <td>{l.opening_text ?? "first count"}</td>
              <td>{l.received_text}</td>
              <td>{l.sold_text}</td>
              <td>{l.waste_text}</td>
              <td>{l.expected_text}</td>
              <td>
                <strong>{l.counted_text}</strong>
              </td>
              <td className={Number(l.variance) < 0 ? "warn" : ""}>{l.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Count = { full: string; tenths: number; ml: string };

/** Count sealed bottles (or kg, pieces) and the open bottle in tenths, or the ml left in it
 * as measured. Faida doesn't show what it expects until the count is saved, so the count
 * isn't nudged. The result is the stock sheet since each item's last count. */
function StockTakeView({ items, isOwner, onReload, onDone }: { items: StockItem[]; isOwner: boolean; onReload: () => void; onDone: () => void }) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<StockItem | null>(null);
  const [station, setStation] = useState<"bar" | "kitchen">("bar");
  const [counts, setCounts] = useState<Record<string, Count>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [result, setResult] = useState<{ lines: Variance[]; total: number | null } | null>(null);
  const [kind, setKind] = useState<TakeKind | null>(null);
  const [whose, setWhose] = useState<{ id: string; name: string } | null>(null);
  const [staff, setStaff] = useState<{ id: string; name: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getActiveStaff().then(setStaff, () => {});
  }, []);
  const shown = useMemo(() => items.filter((i) => i.station === station && i.active), [items, station]);
  const counted = Object.keys(counts).length;
  const sel = items.find((i) => i.id === selected);
  const set = (id: string, c: Partial<Count>) => setCounts({ ...counts, [id]: { ...{ full: "", tenths: 0, ml: "" }, ...counts[id], ...c } });

  const save = () =>
    stockTake(
      undefined,
      Object.entries(counts).map(([id, c]) => ({ stock_item_id: id, full: num(c.full), open_tenths: c.tenths, open_ml: c.ml ? num(c.ml) : undefined })),
      kind ?? "count",
      whose?.id,
    ).then((r) => setResult({ lines: r.lines, total: r.total_value }), (e) => setError(errorText(e)));

  const title = kind === "opening" ? `Opening stock: ${whose?.name}'s shift` : kind === "closing" ? `Closing stock: ${whose?.name}'s hand-over` : "Stock take";
  if (!kind || (kind !== "count" && !whose)) {
    return (
      <div style={{ maxWidth: 720 }}>
        <h2 className="section-title">{kind ? (kind === "opening" ? "Opening count: whose shift is starting?" : "Closing count: who is handing over?") : "What are you counting?"}</h2>
        {!kind ? (
          <div className="choice-list">
            <button className="choice" onClick={() => setKind("opening")}>
              <strong>Opening stock</strong>
              <div className="muted">At the start of someone's shift: what they take over.</div>
            </button>
            <button className="choice" onClick={() => setKind("closing")}>
              <strong>Closing stock (hand-over)</strong>
              <div className="muted">Before their cash hand-over: what they hand over. It is also the next person's opening.</div>
            </button>
            <button className="choice" onClick={() => setKind("count")}>
              <strong>Spot check / full stock take</strong>
              <div className="muted">Any other time, or the first count of everything.</div>
            </button>
          </div>
        ) : (
          <div className="choice-grid">
            {staff.map((p) => (
              <button key={p.id} className="choice" onClick={() => setWhose(p)}>
                {p.name}
              </button>
            ))}
          </div>
        )}
        <button className="btn btn-quiet" style={{ marginTop: 16 }} onClick={kind ? () => setKind(null) : onDone}>
          {kind ? "Back" : "Cancel"}
        </button>
      </div>
    );
  }

  if (result) {
    return (
      <>
        <h2 className="section-title">{title}: {result.lines.length} {result.lines.length === 1 ? "item" : "items"} counted</h2>
        {result.total !== null && (
          <p style={{ fontSize: 22, fontWeight: 700 }} className={result.total < 0 ? "warn" : ""}>
            Variance at buying price: {result.total < 0 ? "−" : ""}KSh {formatKsh(Math.abs(result.total))}
          </p>
        )}
        <p className="muted" style={{ marginTop: 0 }}>
          Opening is the last count. Opening + received − sold − waste = expected. Use Print / PDF above to keep the stock sheet.
        </p>
        <StockSheet lines={result.lines} />
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
          <span className="grow muted">
            <strong>{title}</strong> · {counted} counted
          </span>
          {isOwner && (
            <button className="btn btn-quiet" onClick={() => setAdding(true)}>
              + New item
            </button>
          )}
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
                  {c && i.bottle_size ? (c.ml ? ` + ${c.ml} ml` : ` + ${c.tenths}/10`) : ""}
                </strong>
              </button>
              {i.bottle_size !== null && (
                <label className="tenths">
                  <span className="muted">open bottle</span>
                  <input
                    type="range"
                    min={0}
                    max={9}
                    step={1}
                    value={c?.tenths ?? 0}
                    disabled={!!c?.ml}
                    onChange={(e) => set(i.id, { tenths: Number(e.target.value) })}
                  />
                  <strong>{c?.ml ? "" : `${c?.tenths ?? 0}/10`}</strong>
                  <span className="muted">or ml left</span>
                  <input
                    className="text-input take-ml"
                    inputMode="numeric"
                    placeholder={`0–${i.bottle_size}`}
                    value={c?.ml ?? ""}
                    onChange={(e) => set(i.id, { ml: e.target.value.replace(/\D/g, "").slice(0, 4) })}
                  />
                </label>
              )}
              {isOwner && (
                <button className="btn btn-quiet take-edit" onClick={() => setEditing(i)} aria-label={`Change ${i.name}`}>
                  <Pencil size={18} />
                </button>
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
      {adding && <NewItemDialog onDone={() => (setAdding(false), onReload())} onClose={() => setAdding(false)} />}
      {editing && <ItemDialog item={editing} isOwner={isOwner} onChanged={() => (setEditing(null), onReload())} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ItemDialog({ item, isOwner, onChanged, onClose }: { item: StockItem; isOwner: boolean; onChanged: () => void; onClose: () => void }) {
  const [moves, setMoves] = useState<StockMovement[] | null>(null);
  const [f, setF] = useState({
    name: item.name,
    bottle_size: item.bottle_size ? String(item.bottle_size) : "",
    pack_name: item.pack_name ?? "",
    pack_size: item.pack_size ? String(item.pack_size) : "",
    price: item.buying_price ?? "",
    reorder: String(Number(item.reorder_level) / (item.bottle_size ?? (item.unit === "ml" || item.unit === "g" ? 1000 : 1))),
  });
  const [selling, setSelling] = useState(item.selling.map((s) => ({ ...s, price: String(s.price) })));
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const resized = item.unit === "ml" && item.bottle_size !== null && f.bottle_size !== "" && Number(f.bottle_size) !== item.bottle_size;
  const save = async () => {
    try {
      await updateStockItem(item.id, {
        name: f.name.trim() || undefined,
        bottle_size: resized ? Number(f.bottle_size) : undefined,
        pack_name: f.pack_name.trim() || undefined,
        pack_size: f.pack_size ? Number(f.pack_size) : undefined,
        buying_price: f.price || undefined,
        reorder_level: f.reorder || undefined,
      });
      for (const s of selling) {
        const before = item.selling.find((b) => b.option_id === s.option_id);
        if (s.price !== "" && Number(s.price) !== before?.price) await updateOption(s.option_id, { price: Number(s.price) });
      }
      onChanged();
    } catch (e) {
      setError(errorText(e));
    }
  };
  const remove = () => updateStockItem(item.id, { active: false }).then(onChanged, (e) => setError(errorText(e)));
  useEffect(() => {
    getMovements(item.id).then(setMoves, (e) => setError(errorText(e)));
  }, [item.id]);
  const field = (label: string, k: keyof typeof f, mode: "text" | "numeric" | "decimal" = "text") => (
    <label className="form-field grow" style={{ minWidth: 0, flexBasis: 0 }}>
      <span>{label}</span>
      <input className="text-input" style={{ width: "100%", minWidth: 0 }} inputMode={mode} value={f[k]} onChange={set(k)} />
    </label>
  );
  return (
    <Modal title={`${item.name}: ${item.level_text}`} onClose={onClose} wide>
      {isOwner && (
        <>
          <div className="row" style={{ alignItems: "flex-end" }}>
            {field("Name", "name")}
            {item.unit === "ml" && item.bottle_size !== null && field("ml in one bottle", "bottle_size", "numeric")}
          </div>
          {resized && Number(item.level) > 0 && (
            <p className="warn" style={{ margin: 0 }}>
              The {Number(item.level).toLocaleString()} ml in stock stay as they are: about {(Number(item.level) / Number(f.bottle_size)).toFixed(1)} bottles of{" "}
              {f.bottle_size} ml. Count it again after saving.
            </p>
          )}
          <div className="row" style={{ alignItems: "flex-end" }}>
            {field("Pack it comes in", "pack_name")}
            {field(`${plural(item.counting_unit)} per pack`, "pack_size", "numeric")}
            {field(`Buying price per ${item.counting_unit}`, "price", "decimal")}
            {field(`Warn when below (${plural(item.counting_unit)})`, "reorder", "decimal")}
          </div>
          {selling.length > 0 && (
            <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
              {selling.map((s, i) => (
                <label key={s.option_id} className="form-field" style={{ minWidth: 160 }}>
                  <span>Selling price: {s.name}</span>
                  <input
                    className="text-input"
                    inputMode="numeric"
                    value={s.price}
                    onChange={(e) => setSelling(selling.map((x, j) => (j === i ? { ...x, price: e.target.value.replace(/\D/g, "") } : x)))}
                  />
                </label>
              ))}
            </div>
          )}
          {!selling.length && <p className="muted">Not sold on the menu. Link it under Recipes, or add it from New item.</p>}
          <div className="row">
            {removing ? (
              <>
                <span className="warn grow">Remove {item.name} from the stock list? Its history is kept.</span>
                <button className="btn btn-quiet" onClick={() => setRemoving(false)}>
                  Keep
                </button>
                <button className="btn btn-red" onClick={remove}>
                  REMOVE
                </button>
              </>
            ) : (
              <>
                <button className="btn btn-quiet" onClick={() => setRemoving(true)}>
                  Remove from stock
                </button>
                <span className="grow" />
                <button className="btn btn-primary" disabled={!f.name.trim()} onClick={save}>
                  SAVE
                </button>
              </>
            )}
          </div>
        </>
      )}
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
  const counting = form.unit === "ml" ? (form.bottle_size ? "bottle" : "litre") : form.unit === "g" ? "kg" : form.unit;
  const spirit = form.unit === "ml" && !!form.bottle_size;
  const sold = !!form.price || (spirit && !!form.tot_price);
  const set = (k: keyof typeof form, v: string) => {
    const next = { ...form, [k]: v };
    setForm(next);
    // A first selling price: guess the menu category (beers, spirits), the owner can change it.
    if (!category && (k === "price" || k === "tot_price") && v) {
      const guess = next.unit === "ml" && next.bottle_size ? /spirit/i : next.unit === "bottle" && next.station === "bar" ? /beer/i : null;
      setCategory(categories.find((c) => guess?.test(c.name))?.id ?? null);
    }
  };
  const save = () => {
    if (sold && !category) return setError("Choose the menu category it sells under.");
    return createStockItem({
      name: form.name.trim(),
      station: form.station,
      unit: form.unit,
      bottle_size: form.unit === "ml" && form.bottle_size ? num(form.bottle_size) : null,
      pack_name: form.pack_name.trim() || null,
      pack_size: form.pack_size ? num(form.pack_size) : null,
      buying_price: form.buying_price || null,
      reorder_level: form.reorder_level || 0,
      sell: sold && category ? { category_id: category, price: form.price ? num(form.price) : null, tot_price: spirit && form.tot_price ? num(form.tot_price) : null } : null,
    }).then(onDone, (e) => setError(errorText(e)));
  };
  const field = (k: keyof typeof form, label: string, placeholder: string, mode: "text" | "decimal" | "numeric" = "text") => (
    <label className="form-field grow" style={{ minWidth: 0, flexBasis: 0 }}>
      <span>{label}</span>
      <input
        className="text-input"
        style={{ width: "100%", minWidth: 0 }}
        placeholder={placeholder}
        inputMode={mode}
        value={form[k]}
        onChange={(e) => set(k, mode === "numeric" ? e.target.value.replace(/\D/g, "") : e.target.value)}
      />
    </label>
  );
  return (
    <Modal title="New stock item" onClose={onClose} wide>
      {field("name", "Name", "e.g. Tusker 500ml")}
      <h3 className="form-title">Kept at</h3>
      <div className="row">
        {(["bar", "kitchen"] as const).map((s) => (
          <button key={s} className={`btn grow ${form.station === s ? "btn-primary" : "btn-quiet"}`} onClick={() => set("station", s)}>
            {s === "bar" ? "Bar" : "Kitchen"}
          </button>
        ))}
      </div>
      <h3 className="form-title">Counted in</h3>
      <div className="row">
        {(["bottle", "ml", "g", "piece"] as const).map((u) => (
          <button key={u} className={`btn grow ${form.unit === u ? "btn-primary" : "btn-quiet"}`} onClick={() => set("unit", u)}>
            {{ bottle: "Bottles (beer, soda)", ml: "ml (spirits, oil)", g: "Grams", piece: "Pieces" }[u]}
          </button>
        ))}
      </div>
      {form.unit === "ml" && field("bottle_size", "Bottle size in ml (spirits; empty for oil)", "e.g. 750", "numeric")}
      <h3 className="form-title">Prices (KSh)</h3>
      <div className="row" style={{ alignItems: "flex-end" }}>
        {field("buying_price", `Buying price per ${counting}`, "what you pay", "decimal")}
        {field("price", `Selling price per ${counting}`, "empty: not sold", "numeric")}
        {spirit && field("tot_price", "Selling price per tot", "empty: not by the tot", "numeric")}
      </div>
      {sold ? (
        <>
          <h3 className="form-title">Menu category it sells under</h3>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {categories.map((c) => (
              <button key={c.id} className={`btn ${category === c.id ? "btn-primary" : "btn-quiet"}`} onClick={() => setCategory(c.id)}>
                {c.name}
              </button>
            ))}
          </div>
        </>
      ) : (
        <p className="muted">No selling price: it is kept in stock but not on the menu (an ingredient, like oil).</p>
      )}
      <h3 className="form-title">Optional</h3>
      <div className="row" style={{ alignItems: "flex-end" }}>
        {field("pack_name", "Pack it comes in", "e.g. crate")}
        {field("pack_size", `${plural(counting).replace(/^./, (c) => c.toUpperCase())} per pack`, "e.g. 25", "decimal")}
        {field("reorder_level", `Warn when below (${plural(counting)})`, "e.g. 24", "decimal")}
      </div>
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
