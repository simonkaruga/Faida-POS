import { Eye, EyeOff, ImagePlus, KeyRound, Pencil, Plus, Star, Trash2, UserMinus, UserPlus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import {
  addModOption,
  addOption,
  ApiError,
  createCategory,
  createGroup,
  createItem,
  createRule,
  createStaff,
  createTable,
  deactivateStaff,
  getFloor,
  getManageMenu,
  getSettings,
  getStaff,
  getStock,
  removeItemImage,
  resetPin,
  setCombo,
  setItemGroups,
  setItemImage,
  updateCategory,
  updateGroup,
  updateItem,
  updateModOption,
  updateOption,
  updateRule,
  updateSettings,
  updateStaff,
  updateTable,
  type ManageItem,
  type ManageMenu,
  type PriceRuleRow,
  type Role,
  type Session,
  type Settings,
  type StaffRow,
  type StockItem,
  type TableRow,
} from "../services/api";
import { getStartScreen, setStartScreen } from "../shared/device";
import { Keypad } from "../shared/Keypad";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";
import { toast } from "../shared/Toast";
import { useThemeChoice } from "../shared/theme";

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const ROLES: Role[] = ["waiter", "supervisor", "owner"];
const ROLE_NAME = { owner: "Owner", supervisor: "Supervisor", waiter: "Waiter" } as const;

function useData<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = () => load().then(setData, (e) => setError(errorText(e)));
  useEffect(() => {
    reload();
  }, []);
  return { data, error, reload };
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="form-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" className={`toggle ${on ? "on" : ""}`} onClick={() => onChange(!on)} aria-pressed={on}>
      <span className="toggle-knob" />
      {label}
    </button>
  );
}

/* ---------- Menu ---------- */

export function MenuEditor() {
  const { data: menu, error, reload } = useData<ManageMenu>(getManageMenu);
  const [category, setCategory] = useState<string | null>(null);
  const [editing, setEditing] = useState<ManageItem | "new" | null>(null);
  const [renaming, setRenaming] = useState<{ id: string | null; name: string } | null>(null);
  if (!menu) return <div className="screen-loading">{error ?? <span className="spinner" />}</div>;
  const current = category ?? menu.categories[0]?.id ?? null;
  const items = menu.items.filter((i) => i.category_id === current);
  const run = (p: Promise<unknown>, done?: string) => p.then(() => (done && toast(done), reload()), (e) => toast(errorText(e), "error"));

  return (
    <div className="setup-split">
      <aside className="setup-list">
        {menu.categories.map((c) => (
          <button key={c.id} className={`setup-link ${current === c.id ? "on" : ""} ${c.active ? "" : "hidden-row"}`} onClick={() => setCategory(c.id)}>
            <span className="grow">{c.name}</span>
            <span className="muted">{menu.items.filter((i) => i.category_id === c.id && i.active).length}</span>
          </button>
        ))}
        <button className="btn btn-quiet" onClick={() => setRenaming({ id: null, name: "" })}>
          <Plus size={18} /> Category
        </button>
      </aside>
      <section className="grow">
        {current && (
          <div className="row" style={{ marginBottom: 12 }}>
            <h2 className="section-title grow">{menu.categories.find((c) => c.id === current)?.name}</h2>
            <button className="btn btn-quiet" onClick={() => setRenaming({ id: current, name: menu.categories.find((c) => c.id === current)!.name })}>
              <Pencil size={18} /> Rename
            </button>
            <button
              className="btn btn-quiet"
              onClick={() => {
                const c = menu.categories.find((x) => x.id === current)!;
                run(updateCategory(c.id, { active: !c.active }), c.active ? "Category hidden from the counter" : "Category shown");
              }}
            >
              {menu.categories.find((c) => c.id === current)?.active ? <EyeOff size={18} /> : <Eye size={18} />}
              {menu.categories.find((c) => c.id === current)?.active ? "Hide" : "Show"}
            </button>
            <button className="btn btn-primary" onClick={() => setEditing("new")}>
              <Plus size={20} /> New item
            </button>
          </div>
        )}
        <div className="list-table">
          {items.map((i) => (
            <button key={i.id} className={`list-row ${i.active ? "" : "hidden-row"}`} onClick={() => setEditing(i)}>
              {i.image ? <img className="thumb" src={i.image} alt="" /> : <span className="thumb empty" />}
              <strong style={{ minWidth: 200 }}>{i.name}</strong>
              <span className="grow muted">
                {i.options.filter((o) => o.active).map((o) => `${o.label ? `${o.label} ` : ""}${formatKsh(o.price)}`).join(" · ")}
              </span>
              {i.favourite && <Star size={18} color="var(--yellow)" />}
              {i.is_combo && <span className="pill blue">Combo</span>}
              {i.modifier_group_ids.length > 0 && <span className="pill">{i.modifier_group_ids.length} choices</span>}
              {!i.available && <span className="pill red">Sold out</span>}
              {!i.active && <span className="pill">Hidden</span>}
              <span className="pill">{i.station === "bar" ? "Bar" : "Kitchen"}</span>
            </button>
          ))}
          {!items.length && <p className="muted">No items in this category yet.</p>}
        </div>
      </section>
      {renaming && (
        <Modal title={renaming.id ? "Rename category" : "New category"} onClose={() => setRenaming(null)}>
          <input className="text-input" autoFocus value={renaming.name} maxLength={60} onChange={(e) => setRenaming({ ...renaming, name: e.target.value })} />
          <div className="row row-end">
            <button
              className="btn btn-primary"
              disabled={!renaming.name.trim()}
              onClick={() =>
                run(renaming.id ? updateCategory(renaming.id, { name: renaming.name.trim() }) : createCategory(renaming.name.trim(), menu.categories.length), "Saved").then(() =>
                  setRenaming(null),
                )
              }
            >
              SAVE
            </button>
          </div>
        </Modal>
      )}
      {editing && current && (
        <ItemEditor menu={menu} item={editing === "new" ? null : editing} categoryId={current} onDone={() => (setEditing(null), reload())} onClose={() => setEditing(null)} />
      )}
    </div>
  );
}

function ItemEditor({ menu, item, categoryId, onDone, onClose }: { menu: ManageMenu; item: ManageItem | null; categoryId: string; onDone: () => void; onClose: () => void }) {
  const [name, setName] = useState(item?.name ?? "");
  const [cat, setCat] = useState(item?.category_id ?? categoryId);
  const [station, setStation] = useState<"bar" | "kitchen">(item?.station ?? "bar");
  const [favourite, setFavourite] = useState(item?.favourite ?? false);
  const [active, setActive] = useState(item?.active ?? true);
  const [options, setOptions] = useState(item?.options.map((o) => ({ ...o, price: String(o.price) })) ?? [{ id: "", label: "", price: "", sort_order: 0, active: true }]);
  const [groups, setGroups] = useState<string[]>(item?.modifier_group_ids ?? []);
  const [combo, setComboParts] = useState(item?.combo ?? []);
  const [image, setImage] = useState(item?.image ?? null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const allOptions = menu.items
    .filter((i) => !i.is_combo && i.id !== item?.id)
    .flatMap((i) => i.options.filter((o) => o.active).map((o) => ({ id: o.id, name: o.label ? `${i.name} - ${o.label}` : i.name })));

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const priced = options.filter((o) => o.price !== "");
      if (!name.trim() || !priced.length) throw new ApiError(422, "Give the item a name and at least one price.");
      let id = item?.id;
      if (!id) {
        id = (await createItem({ category_id: cat, name: name.trim(), station, favourite, options: priced.map((o) => ({ label: o.label.trim(), price: Number(o.price) })) })).id;
      } else {
        await updateItem(id, { name: name.trim(), category_id: cat, station, favourite, active });
        for (const o of priced) {
          const before = item!.options.find((x) => x.id === o.id);
          if (!o.id) await addOption(id, { label: o.label.trim(), price: Number(o.price) });
          else if (before && (before.label !== o.label.trim() || before.price !== Number(o.price) || before.active !== o.active))
            await updateOption(o.id, { label: o.label.trim(), price: Number(o.price), active: o.active });
        }
      }
      if (JSON.stringify(groups) !== JSON.stringify(item?.modifier_group_ids ?? [])) await setItemGroups(id, groups);
      if (JSON.stringify(combo) !== JSON.stringify(item?.combo ?? [])) await setCombo(id, combo);
      toast(`${name.trim()} saved`);
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const pickImage = (file: File | undefined) => {
    if (!file || !item) return;
    const reader = new FileReader();
    reader.onload = () =>
      setItemImage(item.id, String(reader.result)).then((r) => (setImage(r.image), toast("Picture saved")), (e) => setError(errorText(e)));
    reader.readAsDataURL(file);
  };

  return (
    <Modal title={item ? `Edit ${item.name}` : "New item"} onClose={onClose} wide>
      <div className="form-grid">
        <Field label="Name">
          <input className="text-input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} autoFocus={!item} />
        </Field>
        <Field label="Category">
          <select className="text-input" value={cat} onChange={(e) => setCat(e.target.value)}>
            {menu.categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <div className="segmented">
          {(["bar", "kitchen"] as const).map((st) => (
            <button key={st} className={station === st ? "on" : ""} onClick={() => setStation(st)}>
              {st === "bar" ? "Bar slip" : "Kitchen ticket"}
            </button>
          ))}
        </div>
        <Toggle on={favourite} onChange={setFavourite} label="Favourite" />
        {item && <Toggle on={active} onChange={setActive} label="On the menu" />}
      </div>

      <h3 className="form-title">Sizes and prices</h3>
      {options.map((o, i) => (
        <div key={i} className={`row ${o.active ? "" : "hidden-row"}`}>
          <input className="text-input grow" placeholder={options.length > 1 ? "Size, e.g. Single tot" : "Size (leave empty if only one)"} value={o.label} maxLength={40} onChange={(e) => setOptions(options.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
          <input className="text-input" style={{ width: 150 }} inputMode="numeric" placeholder="Price" value={o.price} onChange={(e) => setOptions(options.map((x, j) => (j === i ? { ...x, price: e.target.value.replace(/\D/g, "") } : x)))} />
          {o.id && (
            <button className="btn btn-quiet" onClick={() => setOptions(options.map((x, j) => (j === i ? { ...x, active: !x.active } : x)))}>
              {o.active ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          )}
        </div>
      ))}
      <button className="btn btn-quiet" style={{ alignSelf: "flex-start" }} onClick={() => setOptions([...options, { id: "", label: "", price: "", sort_order: options.length, active: true }])}>
        <Plus size={18} /> Another size
      </button>

      {menu.modifier_groups.length > 0 && (
        <>
          <h3 className="form-title">Choices asked when ordering</h3>
          <div className="chip-row">
            {menu.modifier_groups.map((g) => (
              <button key={g.id} className={`chip ${groups.includes(g.id) ? "on" : ""}`} onClick={() => setGroups(groups.includes(g.id) ? groups.filter((x) => x !== g.id) : [...groups, g.id])}>
                {g.name} {g.min_select > 0 ? "(required)" : ""}
              </button>
            ))}
          </div>
        </>
      )}

      <h3 className="form-title">Combo parts {combo.length === 0 && <span className="muted">(none: a normal item)</span>}</h3>
      {combo.map((p, i) => (
        <div key={i} className="row">
          <select className="text-input grow" value={p.sell_option_id} onChange={(e) => setComboParts(combo.map((x, j) => (j === i ? { ...x, sell_option_id: e.target.value } : x)))}>
            {allOptions.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
          <input className="text-input" style={{ width: 90 }} inputMode="numeric" value={p.quantity} onChange={(e) => setComboParts(combo.map((x, j) => (j === i ? { ...x, quantity: Number(e.target.value.replace(/\D/g, "")) || 1 } : x)))} />
          <button className="btn btn-quiet" onClick={() => setComboParts(combo.filter((_, j) => j !== i))} aria-label="Remove part">
            <Trash2 size={18} />
          </button>
        </div>
      ))}
      <button className="btn btn-quiet" style={{ alignSelf: "flex-start" }} disabled={!allOptions.length} onClick={() => setComboParts([...combo, { sell_option_id: allOptions[0].id, quantity: 1 }])}>
        <Plus size={18} /> Add a part
      </button>

      {item && (
        <>
          <h3 className="form-title">Picture on the tile</h3>
          <div className="row">
            {image ? <img className="thumb big" src={image} alt="" /> : <span className="thumb big empty" />}
            <label className="btn btn-quiet">
              <ImagePlus size={18} /> Choose picture
              <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(e) => pickImage(e.target.files?.[0])} />
            </label>
            {image && (
              <button className="btn btn-quiet" onClick={() => removeItemImage(item.id).then(() => setImage(null))}>
                <Trash2 size={18} /> Remove
              </button>
            )}
          </div>
        </>
      )}
      <p className="error-text">{error ?? ""}</p>
      <div className="row row-end">
        <button className="btn btn-primary" disabled={busy} onClick={save}>
          SAVE ITEM
        </button>
      </div>
    </Modal>
  );
}

/* ---------- Choices (modifiers) and happy hour ---------- */

export function ChoicesEditor() {
  const { data: menu, error, reload } = useData<ManageMenu>(getManageMenu);
  const [stock, setStock] = useState<StockItem[]>([]);
  const [group, setGroup] = useState<{ name: string; required: boolean; max: string } | null>(null);
  const [optionFor, setOptionFor] = useState<{ groupId: string; label: string; price: string; stock: string; qty: string } | null>(null);
  const [rule, setRule] = useState<(Omit<PriceRuleRow, "id" | "active"> & { id?: string }) | null>(null);
  useEffect(() => {
    getStock().then(setStock, () => {});
  }, []);
  if (!menu) return <div className="screen-loading">{error ?? <span className="spinner" />}</div>;
  const run = (p: Promise<unknown>, done: string) => p.then(() => (toast(done), reload()), (e) => toast(errorText(e), "error"));

  return (
    <div className="setup-cols">
      <section>
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 className="section-title grow">Choices (mixers, sides, how cooked)</h2>
          <button className="btn btn-primary" onClick={() => setGroup({ name: "", required: false, max: "1" })}>
            <Plus size={20} /> New choice
          </button>
        </div>
        {menu.modifier_groups.map((g) => (
          <div key={g.id} className={`rp-section ${g.active ? "" : "hidden-row"}`} style={{ marginBottom: 10 }}>
            <div className="row">
              <strong className="grow" style={{ fontSize: 19 }}>
                {g.name}
              </strong>
              <span className="pill">{g.min_select > 0 ? "required" : "optional"}</span>
              <span className="pill">up to {g.max_select}</span>
              <button className="btn btn-quiet" onClick={() => run(updateGroup(g.id, { active: !g.active }), g.active ? "Hidden" : "Shown")}>
                {g.active ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            <div className="chip-row" style={{ marginTop: 8 }}>
              {g.options.map((o) => (
                <span key={o.id} className="chip on">
                  {o.label}
                  {o.price > 0 && ` +${formatKsh(o.price)}`}
                  <button className="chip-x" onClick={() => run(updateModOption(o.id, { active: false }), `${o.label} removed`)} aria-label={`Remove ${o.label}`}>
                    ×
                  </button>
                </span>
              ))}
              <button className="chip" onClick={() => setOptionFor({ groupId: g.id, label: "", price: "0", stock: "", qty: "1" })}>
                <Plus size={16} /> Option
              </button>
            </div>
          </div>
        ))}
        {!menu.modifier_groups.length && <p className="muted">No choices yet. Add "Mixer" for spirits or "Side" for mains.</p>}
      </section>
      <section>
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 className="section-title grow">Happy hour</h2>
          <button className="btn btn-primary" onClick={() => setRule({ name: "Happy hour", percent_off: 20, days: [0, 1, 2, 3, 4], start_time: "17:00", end_time: "19:00", category_ids: [] })}>
            <Plus size={20} /> New offer
          </button>
        </div>
        {menu.price_rules.map((r) => (
          <button key={r.id} className={`list-row ${r.active ? "" : "hidden-row"}`} style={{ width: "100%", marginBottom: 8 }} onClick={() => setRule(r)}>
            <strong className="grow" style={{ whiteSpace: "nowrap" }}>
              {r.percent_off}% off · {r.name}
            </strong>
            <span className="muted">
              {r.days.map((d) => DAYS[d]).join(" ")} · {r.start_time}–{r.end_time}
            </span>
            <span className="pill">{r.category_ids.length ? r.category_ids.map((c) => menu.categories.find((x) => x.id === c)?.name).join(", ") : "Everything"}</span>
            {!r.active && <span className="pill">Off</span>}
          </button>
        ))}
        {!menu.price_rules.length && <p className="muted">No offers. Prices change automatically during an offer, and back after.</p>}
      </section>

      {group && (
        <Modal title="New choice" onClose={() => setGroup(null)}>
          <Field label="Name, e.g. Mixer">
            <input className="text-input" autoFocus value={group.name} maxLength={40} onChange={(e) => setGroup({ ...group, name: e.target.value })} />
          </Field>
          <div className="row">
            <Toggle on={group.required} onChange={(v) => setGroup({ ...group, required: v })} label="Must choose one" />
            <Field label="Most that can be chosen">
              <input className="text-input" style={{ width: 90 }} inputMode="numeric" value={group.max} onChange={(e) => setGroup({ ...group, max: e.target.value.replace(/\D/g, "") })} />
            </Field>
          </div>
          <div className="row row-end">
            <button
              className="btn btn-primary"
              disabled={!group.name.trim()}
              onClick={() => run(createGroup({ name: group.name.trim(), min_select: group.required ? 1 : 0, max_select: Number(group.max) || 1 }), "Choice added").then(() => setGroup(null))}
            >
              SAVE
            </button>
          </div>
        </Modal>
      )}
      {optionFor && (
        <Modal title="New option" onClose={() => setOptionFor(null)}>
          <div className="form-grid">
            <Field label="Label, e.g. Coke">
              <input className="text-input" autoFocus value={optionFor.label} maxLength={40} onChange={(e) => setOptionFor({ ...optionFor, label: e.target.value })} />
            </Field>
            <Field label="Extra price (KSh)">
              <input className="text-input" inputMode="numeric" value={optionFor.price} onChange={(e) => setOptionFor({ ...optionFor, price: e.target.value.replace(/\D/g, "") })} />
            </Field>
            <Field label="Takes from stock (optional)">
              <select className="text-input" value={optionFor.stock} onChange={(e) => setOptionFor({ ...optionFor, stock: e.target.value })}>
                <option value="">Nothing</option>
                {stock.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
            {optionFor.stock && (
              <Field label={`How much (${stock.find((s) => s.id === optionFor.stock)?.unit === "bottle" ? "bottles" : stock.find((s) => s.id === optionFor.stock)?.unit})`}>
                <input className="text-input" inputMode="decimal" value={optionFor.qty} onChange={(e) => setOptionFor({ ...optionFor, qty: e.target.value })} />
              </Field>
            )}
          </div>
          <div className="row row-end">
            <button
              className="btn btn-primary"
              disabled={!optionFor.label.trim()}
              onClick={() =>
                run(
                  addModOption(optionFor.groupId, {
                    label: optionFor.label.trim(),
                    price: Number(optionFor.price) || 0,
                    stock_item_id: optionFor.stock || null,
                    stock_quantity: optionFor.stock ? Number(optionFor.qty) || 1 : null,
                  }),
                  "Option added",
                ).then(() => setOptionFor(null))
              }
            >
              SAVE
            </button>
          </div>
        </Modal>
      )}
      {rule && (
        <Modal title={rule.id ? "Edit offer" : "New offer"} onClose={() => setRule(null)} wide>
          <div className="form-grid">
            <Field label="Name">
              <input className="text-input" value={rule.name} maxLength={40} onChange={(e) => setRule({ ...rule, name: e.target.value })} />
            </Field>
            <Field label="Percent off">
              <input className="text-input" inputMode="numeric" value={rule.percent_off} onChange={(e) => setRule({ ...rule, percent_off: Number(e.target.value.replace(/\D/g, "")) || 0 })} />
            </Field>
            <Field label="From">
              <input className="text-input" type="time" value={rule.start_time} onChange={(e) => setRule({ ...rule, start_time: e.target.value })} />
            </Field>
            <Field label="To (can be after midnight)">
              <input className="text-input" type="time" value={rule.end_time} onChange={(e) => setRule({ ...rule, end_time: e.target.value })} />
            </Field>
          </div>
          <h3 className="form-title">Days</h3>
          <div className="chip-row">
            {DAYS.map((d, i) => (
              <button key={d} className={`chip ${rule.days.includes(i) ? "on" : ""}`} onClick={() => setRule({ ...rule, days: rule.days.includes(i) ? rule.days.filter((x) => x !== i) : [...rule.days, i] })}>
                {d}
              </button>
            ))}
          </div>
          <h3 className="form-title">On (none chosen: the whole menu)</h3>
          <div className="chip-row">
            {menu.categories.map((c) => (
              <button
                key={c.id}
                className={`chip ${rule.category_ids.includes(c.id) ? "on" : ""}`}
                onClick={() => setRule({ ...rule, category_ids: rule.category_ids.includes(c.id) ? rule.category_ids.filter((x) => x !== c.id) : [...rule.category_ids, c.id] })}
              >
                {c.name}
              </button>
            ))}
          </div>
          <div className="row row-end">
            {rule.id && (
              <button
                className="btn btn-quiet"
                onClick={() => {
                  const r = menu.price_rules.find((x) => x.id === rule.id)!;
                  run(updateRule(r.id, { active: !r.active }), r.active ? "Offer switched off" : "Offer switched on").then(() => setRule(null));
                }}
              >
                {menu.price_rules.find((x) => x.id === rule.id)?.active ? "Switch off" : "Switch on"}
              </button>
            )}
            <button
              className="btn btn-primary"
              onClick={() => {
                const { id, ...body } = rule;
                run(id ? updateRule(id, body) : createRule(body), "Offer saved").then(() => setRule(null));
              }}
            >
              SAVE OFFER
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

/* ---------- Tables ---------- */

export function TablesEditor() {
  const { data, error, reload } = useData(() => getFloor().then((f) => f.tables));
  const [editing, setEditing] = useState<{ id?: string; name: string; section: string } | null>(null);
  if (!data) return <div className="screen-loading">{error ?? <span className="spinner" />}</div>;
  const tables = data as TableRow[];
  const sections = [...new Set(tables.map((t) => t.section))];
  const save = () => {
    if (!editing) return;
    const body = { name: editing.name.trim(), section: editing.section.trim() || "Main" };
    (editing.id ? updateTable(editing.id, body) : createTable({ ...body, sort_order: tables.length })).then(
      () => (toast("Table saved"), setEditing(null), reload()),
      (e) => toast(errorText(e), "error"),
    );
  };
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <p className="muted grow" style={{ margin: 0 }}>
          Optional. Waiters can type any table number on an order, so you don't have to set up every table. Set up the ones you want on
          the floor plan and in sales by section. Hidden tables are kept for history.
        </p>
        <button className="btn btn-primary" onClick={() => setEditing({ name: "", section: sections[0] ?? "Main" })}>
          <Plus size={20} /> New table
        </button>
      </div>
      {sections.map((s) => (
        <div key={s}>
          <h3 className="section-sub">{s}</h3>
          <div className="chip-row">
            {tables
              .filter((t) => t.section === s)
              .map((t) => (
                <button key={t.id} className="chip on big" onClick={() => setEditing({ id: t.id, name: t.name, section: t.section })}>
                  {t.name}
                </button>
              ))}
          </div>
        </div>
      ))}
      {editing && (
        <Modal title={editing.id ? `Edit ${editing.name}` : "New table"} onClose={() => setEditing(null)}>
          <div className="form-grid">
            <Field label="Name">
              <input className="text-input" autoFocus value={editing.name} maxLength={30} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
            </Field>
            <Field label="Section, e.g. Indoor, Garden, VIP">
              <input className="text-input" list="sections" value={editing.section} maxLength={30} onChange={(e) => setEditing({ ...editing, section: e.target.value })} />
              <datalist id="sections">
                {sections.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </Field>
          </div>
          <div className="row row-end">
            {editing.id && (
              <button
                className="btn btn-quiet"
                onClick={() => updateTable(editing.id!, { active: false }).then(() => (toast("Table hidden"), setEditing(null), reload()), (e) => toast(errorText(e), "error"))}
              >
                <EyeOff size={18} /> Hide table
              </button>
            )}
            <button className="btn btn-primary" disabled={!editing.name.trim()} onClick={save}>
              SAVE
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

/* ---------- Staff ---------- */

export function StaffEditor({ session }: { session: Session }) {
  const { data: staff, error, reload } = useData<StaffRow[]>(getStaff);
  const [adding, setAdding] = useState<{ name: string; role: Role } | null>(null);
  const [pinFor, setPinFor] = useState<{ id: string | null; name: string; role?: Role } | null>(null);
  const [pin, setPin] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);
  if (!staff) return <div className="screen-loading">{error ?? <span className="spinner" />}</div>;
  const run = (p: Promise<unknown>, done: string) => p.then(() => (toast(done), reload()), (e) => toast(errorText(e), "error"));

  const savePin = () => {
    if (!pinFor) return;
    const p = pinFor.id ? resetPin(pinFor.id, pin) : createStaff({ name: pinFor.name, role: pinFor.role!, pin });
    p.then(
      () => (toast(pinFor.id ? `New PIN set for ${pinFor.name}` : `${pinFor.name} added`), setPinFor(null), setPin(""), setPinError(null), reload()),
      (e) => (setPinError(errorText(e)), setPin("")),
    );
  };

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <p className="muted grow" style={{ margin: 0 }}>
          Everyone logs in with their own PIN. Staff who leave are deactivated, never deleted, so their history stays.
        </p>
        <button className="btn btn-primary" onClick={() => setAdding({ name: "", role: "waiter" })}>
          <UserPlus size={20} /> Add staff
        </button>
      </div>
      <div className="list-table">
        {staff.map((s) => (
          <div key={s.id} className={`shift-row ${s.active ? "" : "hidden-row"}`}>
            <strong style={{ minWidth: 180 }}>{s.name}</strong>
            {s.active ? (
              <div className="segmented">
                {ROLES.map((r) => (
                  <button key={r} className={s.role === r ? "on" : ""} disabled={s.id === session.staff.id} onClick={() => run(updateStaff(s.id, { role: r }), `${s.name} is now ${ROLE_NAME[r].toLowerCase()}`)}>
                    {ROLE_NAME[r]}
                  </button>
                ))}
              </div>
            ) : (
              <span className="pill">Left {s.deactivated_at ? new Date(s.deactivated_at).toLocaleDateString("en-GB") : ""}</span>
            )}
            <span className="grow" />
            {s.active && (
              <>
                <button className="btn btn-quiet" onClick={() => setPinFor({ id: s.id, name: s.name })}>
                  <KeyRound size={18} /> New PIN
                </button>
                {s.id !== session.staff.id && (
                  <button className="btn btn-quiet" onClick={() => confirm(`Deactivate ${s.name}? Their PIN stops working now.`) && run(deactivateStaff(s.id), `${s.name} deactivated`)}>
                    <UserMinus size={18} /> Has left
                  </button>
                )}
              </>
            )}
          </div>
        ))}
      </div>
      {adding && (
        <Modal title="Add staff" onClose={() => setAdding(null)}>
          <Field label="Name">
            <input className="text-input" autoFocus value={adding.name} maxLength={80} onChange={(e) => setAdding({ ...adding, name: e.target.value })} />
          </Field>
          <div className="segmented">
            {ROLES.map((r) => (
              <button key={r} className={adding.role === r ? "on" : ""} onClick={() => setAdding({ ...adding, role: r })}>
                {ROLE_NAME[r]}
              </button>
            ))}
          </div>
          <div className="row row-end">
            <button className="btn btn-primary" disabled={!adding.name.trim()} onClick={() => (setPinFor({ id: null, name: adding.name.trim(), role: adding.role }), setAdding(null))}>
              NEXT: SET PIN
            </button>
          </div>
        </Modal>
      )}
      {pinFor && (
        <Modal title={`PIN for ${pinFor.name}`} onClose={() => (setPinFor(null), setPin(""))}>
          <p className="muted" style={{ margin: 0 }}>
            4 to 6 digits. Not 1234 or the same digit repeated, and different from everyone else's. Let {pinFor.name} type it.
          </p>
          <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
            <Keypad value={pin} onChange={(v) => (setPin(v), setPinError(null))} onEnter={savePin} enterLabel="SAVE" />
            <div style={{ fontSize: 30, letterSpacing: 8, minWidth: 120 }}>{"•".repeat(pin.length)}</div>
          </div>
          <p className="error-text">{pinError ?? ""}</p>
        </Modal>
      )}
    </>
  );
}

/* ---------- Settings ---------- */

export function SettingsEditor() {
  const { data, error, reload } = useData<Settings>(getSettings);
  const [form, setForm] = useState<Settings | null>(null);
  const [newNote, setNewNote] = useState("");
  const [start, setStart] = useState(getStartScreen);
  const [newEmail, setNewEmail] = useState("");
  const [theme, changeTheme] = useThemeChoice();
  useEffect(() => {
    if (data) setForm(data);
  }, [data]);
  if (!form) return <div className="screen-loading">{error ?? <span className="spinner" />}</div>;
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setForm({ ...form, [k]: v });
  const save = () =>
    updateSettings({
      business_day_cutoff: form.business_day_cutoff.slice(0, 5),
      auto_lock_seconds: form.auto_lock_seconds,
      tot_size_ml: form.tot_size_ml ?? undefined,
      mpesa_code_entry: form.mpesa_code_entry,
      mpesa_till_number: form.mpesa_till_number || undefined,
      receipt_footer: form.receipt_footer,
      note_presets: form.note_presets,
      tab_section: form.tab_section,
      report_emails: form.report_emails,
    }).then(() => (toast("Settings saved"), reload()), (e) => toast(errorText(e), "error"));

  return (
    <div className="settings">
      <section className="rp-section">
        <h3 className="form-title">Business day and screen</h3>
        <div className="form-grid">
          <Field label="Business day ends at (sales after midnight count for the day before)">
            <input className="text-input" type="time" value={form.business_day_cutoff.slice(0, 5)} onChange={(e) => set("business_day_cutoff", e.target.value)} />
          </Field>
          <Field label="Screen locks after (seconds without a touch)">
            <input className="text-input" inputMode="numeric" value={form.auto_lock_seconds} onChange={(e) => set("auto_lock_seconds", Number(e.target.value.replace(/\D/g, "")) || 0)} />
          </Field>
          <Field label="Tot size (ml)">
            <input className="text-input" inputMode="numeric" value={form.tot_size_ml ?? ""} onChange={(e) => set("tot_size_ml", Number(e.target.value.replace(/\D/g, "")) || null)} />
          </Field>
          <Field label="Orders without a set-up table count in section">
            <input className="text-input" value={form.tab_section} maxLength={30} onChange={(e) => set("tab_section", e.target.value)} />
          </Field>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <span className="muted">This screen opens on:</span>
          <div className="segmented">
            {(["menu", "orders"] as const).map((v) => (
              <button key={v} className={start === v ? "on" : ""} onClick={() => (setStartScreen(v), setStart(v), toast(v === "menu" ? "This screen now opens on the menu" : "This screen now opens on the orders"))}>
                {v === "menu" ? "Menu, new order (simplest)" : "List of open orders"}
              </button>
            ))}
          </div>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <span className="muted">This screen:</span>
          <div className="segmented">
            {(["light", "dark", "auto"] as const).map((t) => (
              <button key={t} className={theme === t ? "on" : ""} onClick={() => changeTheme(t)}>
                {{ light: "Bright", dark: "Dark (dim bar)", auto: "Auto: dark 6 pm to 6 am" }[t]}
              </button>
            ))}
          </div>
        </div>
      </section>
      <section className="rp-section">
        <h3 className="form-title">M-Pesa and receipts</h3>
        <div className="form-grid">
          <Field label="M-Pesa till number (printed on bills)">
            <input className="text-input" inputMode="numeric" value={form.mpesa_till_number ?? ""} onChange={(e) => set("mpesa_till_number", e.target.value.replace(/\D/g, "") || null)} />
          </Field>
          <Field label="Receipt thank-you line">
            <input className="text-input" value={form.receipt_footer} maxLength={200} onChange={(e) => set("receipt_footer", e.target.value)} />
          </Field>
        </div>
        <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
          <span className="muted">M-Pesa code entry:</span>
          <div className="segmented">
            {(["last4", "full", "none"] as const).map((m) => (
              <button key={m} className={form.mpesa_code_entry === m ? "on" : ""} onClick={() => set("mpesa_code_entry", m)}>
                {m === "last4" ? "Last 4 characters" : m === "full" ? "Full code" : "None"}
              </button>
            ))}
          </div>
        </div>
      </section>
      <section className="rp-section">
        <h3 className="form-title">Kitchen note buttons</h3>
        <div className="chip-row">
          {form.note_presets.map((n) => (
            <span key={n} className="chip on">
              {n}
              <button className="chip-x" onClick={() => set("note_presets", form.note_presets.filter((x) => x !== n))} aria-label={`Remove ${n}`}>
                ×
              </button>
            </span>
          ))}
          <input className="text-input" style={{ width: 200 }} placeholder="New note" value={newNote} maxLength={40} onChange={(e) => setNewNote(e.target.value)} />
          <button className="btn btn-quiet" disabled={!newNote.trim()} onClick={() => (set("note_presets", [...form.note_presets, newNote.trim()]), setNewNote(""))}>
            <Plus size={18} /> Add
          </button>
        </div>
      </section>
      <section className="rp-section">
        <h3 className="form-title">Email the daily closing to</h3>
        <div className="chip-row">
          {form.report_emails.map((e) => (
            <span key={e} className="chip on">
              {e}
              <button className="chip-x" onClick={() => set("report_emails", form.report_emails.filter((x) => x !== e))} aria-label={`Remove ${e}`}>
                ×
              </button>
            </span>
          ))}
          <input className="text-input" style={{ width: 280 }} type="email" placeholder="name@example.com" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} />
          <button className="btn btn-quiet" disabled={!/^\S+@\S+\.\S+$/.test(newEmail)} onClick={() => (set("report_emails", [...form.report_emails, newEmail.trim()]), setNewEmail(""))}>
            <Plus size={18} /> Add
          </button>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          Sent when the day is closed, with the Excel report, as soon as the counter is online.
        </p>
      </section>
      <div className="row row-end">
        <button className="btn btn-primary" onClick={save}>
          SAVE SETTINGS
        </button>
      </div>
    </div>
  );
}
