import {
  ArrowLeft,
  CheckCircle2,
  ChefHat,
  Clock3,
  Ellipsis,
  GlassWater,
  Minus,
  Plus,
  Printer,
  ReceiptText,
  Search,
  SearchX,
  Send,
  ShoppingBag,
  Trash2,
  TriangleAlert,
  Wallet,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  closeEmpty,
  getBill,
  printBill,
  reprint,
  sendRound,
  type Bill,
  type Menu,
  type MenuItem,
  type Session,
} from "../services/api";
import { categoryColor, categoryIcon, FavouritesIcon, initials, since } from "../shared/look";
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";
import { ReceiptDialog } from "../shared/Receipt";
import { toast } from "../shared/Toast";
import { MoreMenu, VoidDialog } from "./BillActions";
import { groupLines, type LineGroup } from "./billLines";
import { addToDraft, draftTotal, getDraft, saveDraft, type DraftLine } from "./drafts";

type Props = {
  session: Session;
  menu: Menu;
  billId: string;
  onBack: () => void;
  onPay: (billId: string) => void;
  onOpen: (billId: string) => void;
  onSent: (message: string, warning?: boolean) => void;
};

const FAVOURITES = "fav";
const STATION_TICKET = { bar_slip: "Bar slip", kitchen_ticket: "Kitchen ticket", bill: "Bill", receipt: "Receipt" } as const;

export function OrderScreen({ session, menu, billId, onBack, onPay, onOpen, onSent }: Props) {
  const staffId = session.staff.id;
  const [bill, setBill] = useState<Bill | null>(null);
  const [draft, setDraftState] = useState<DraftLine[]>(() => getDraft(staffId, billId));
  const [category, setCategory] = useState<string>(FAVOURITES);
  const [search, setSearch] = useState("");
  const [choosing, setChoosing] = useState<MenuItem | null>(null);
  const [noteFor, setNoteFor] = useState<DraftLine | null>(null);
  const [voiding, setVoiding] = useState<LineGroup | null>(null);
  const [more, setMore] = useState(false);
  const [message, setMessage] = useState<{ text: string; tone: "error" | "ok" } | null>(null);
  const [busy, setBusy] = useState(false);
  const [popped, setPopped] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);

  useEffect(() => {
    getBill(billId).then(setBill, (e) => setMessage({ text: e.message, tone: "error" }));
  }, [billId]);

  const setDraft = (lines: DraftLine[]) => {
    setDraftState(lines);
    saveDraft(staffId, billId, lines);
  };

  const fail = (e: unknown) => setMessage({ text: e instanceof ApiError ? e.message : "Something went wrong.", tone: "error" });

  const items = useMemo(() => {
    const all = menu.categories.flatMap((c) => c.items);
    const q = search.trim().toLowerCase();
    if (q) return all.filter((i) => i.name.toLowerCase().includes(q));
    if (category === FAVOURITES) return all.filter((i) => i.favourite);
    return menu.categories.find((c) => c.id === category)?.items ?? [];
  }, [menu, category, search]);

  const add = (item: MenuItem, optionIndex = 0) => {
    const option = item.options[optionIndex];
    const name = option.label ? `${item.name} - ${option.label}` : item.name;
    setDraft(addToDraft(draft, { optionId: option.id, name, price: option.price, note: null, station: item.station }));
    setMessage(null);
    setPopped(null);
    requestAnimationFrame(() => setPopped(item.id));
  };

  const tapItem = (item: MenuItem) => (item.options.length > 1 ? setChoosing(item) : add(item));

  const changeQty = (line: DraftLine, delta: number) =>
    setDraft(draft.flatMap((l) => (l.key !== line.key ? [l] : l.quantity + delta > 0 ? [{ ...l, quantity: l.quantity + delta }] : [])));

  const send = async () => {
    if (!draft.length || busy) return;
    setBusy(true);
    try {
      const updated = await sendRound(
        billId,
        draft.map((l) => ({ sell_option_id: l.optionId, quantity: l.quantity, note: l.note })),
      );
      setDraft([]);
      const before = new Set(bill?.tickets.map((t) => t.id));
      const newest = updated.tickets.filter((t) => !before.has(t.id) && t.status === "not_printed");
      if (newest.length) {
        onSent(`${updated.place}: sent, but ${newest.map((t) => STATION_TICKET[t.kind]).join(" and ")} NOT PRINTED. Reprint from the bill.`, true);
      } else {
        onSent(`${updated.place}: round sent ✓`);
      }
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const doPrintBill = async () => {
    if (draft.length) return setMessage({ text: "Send the new round first.", tone: "error" });
    try {
      const updated = await printBill(billId);
      setBill(updated);
      const last = updated.tickets[updated.tickets.length - 1];
      if (last.status === "not_printed") toast("Bill NOT printed. Check the printer.", "warning");
      else toast(`Bill for ${updated.place} printed`);
    } catch (e) {
      fail(e);
    }
  };

  // A table opened by mistake shouldn't stay taken: leaving an empty bill closes it.
  const back = async () => {
    if (bill && bill.status === "open" && !bill.lines.length && !bill.paid && !draft.length) {
      await closeEmpty(billId).catch(() => {});
    }
    onBack();
  };

  const pay = () => {
    if (draft.length) return setMessage({ text: "Send the new round first.", tone: "error" });
    if (!bill?.total) return setMessage({ text: "Nothing to pay yet.", tone: "error" });
    onPay(billId);
  };

  const reprintTicket = async (ticketId: string) => {
    try {
      const updated = await reprint(ticketId);
      setBill(updated);
      const t = updated.tickets.find((x) => x.id === ticketId);
      toast(t?.status === "not_printed" ? "Still not printed. Check the printer." : "Printed again", t?.status === "not_printed" ? "warning" : "success");
    } catch (e) {
      fail(e);
    }
  };

  if (!bill) return <main className="screen screen-loading">{message?.text ?? <span className="spinner" />}</main>;

  const rounds = roundsOf(bill);
  const unprinted = bill.tickets.filter((t) => t.status === "not_printed" && t.kind !== "bill");
  const roundTotal = draftTotal(draft);
  const canVoid = session.permissions.void_item !== "deny";
  const inRound = new Map<string, number>();
  for (const l of draft) inRound.set(l.optionId, (inRound.get(l.optionId) ?? 0) + l.quantity);
  const countFor = (item: MenuItem) => item.options.reduce((s, o) => s + (inRound.get(o.id) ?? 0), 0);
  const colorOf = new Map(menu.categories.map((c, i) => [c.id, categoryColor(i)]));
  const categoryOf = new Map(menu.categories.flatMap((c) => c.items.map((i) => [i.id, c.id] as const)));
  const ticketStatus = new Map(bill.tickets.map((t) => [t.id, t.status]));

  return (
    <main className="order">
      <section className="order-menu">
        <div className="order-top">
          <label className="search-box">
            <Search size={20} />
            <input className="text-input" placeholder="Search the menu" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          {search && (
            <button className="btn btn-quiet" onClick={() => setSearch("")}>
              <X size={18} /> Clear
            </button>
          )}
        </div>
        <div className="category-bar">
          <button
            className={`cat ${category === FAVOURITES && !search ? "selected" : ""}`}
            style={{ "--c": "var(--yellow)" } as React.CSSProperties}
            onClick={() => (setCategory(FAVOURITES), setSearch(""))}
          >
            <FavouritesIcon size={20} /> Favourites
          </button>
          {menu.categories.map((c, i) => {
            const Icon = categoryIcon(c.name);
            return (
              <button
                key={c.id}
                className={`cat ${category === c.id && !search ? "selected" : ""}`}
                style={{ "--c": categoryColor(i) } as React.CSSProperties}
                onClick={() => (setCategory(c.id), setSearch(""))}
              >
                <Icon size={20} /> {c.name} <span className="cat-count">{c.items.length}</span>
              </button>
            );
          })}
        </div>
        <div className="item-grid">
          {items.map((item) => {
            const n = countFor(item);
            const Station = item.station === "kitchen" ? ChefHat : GlassWater;
            return (
              <button
                key={item.id}
                className={`item-tile ${popped === item.id ? "pop" : ""}`}
                style={{ "--c": colorOf.get(categoryOf.get(item.id) ?? "") ?? "var(--cat-other)" } as React.CSSProperties}
                onClick={() => tapItem(item)}
              >
                {n > 0 && <span className="item-badge">{n}</span>}
                <span className="item-name">{item.name}</span>
                <span className="item-foot">
                  <span className="item-price">
                    {item.options.length > 1 ? `from ${formatKsh(Math.min(...item.options.map((o) => o.price)))}` : formatKsh(item.options[0].price)}
                  </span>
                  <Station size={16} className="item-station" aria-label={item.station === "kitchen" ? "Kitchen" : "Bar"} />
                </span>
              </button>
            );
          })}
          {!items.length && (
            <div className="empty-state" style={{ gridColumn: "1 / -1" }}>
              <SearchX size={48} />
              {search ? `Nothing on the menu matches "${search}".` : "No items here."}
            </div>
          )}
        </div>
      </section>

      <aside className="bill-panel">
        <header className="bill-head">
          <button className="icon-btn" onClick={back} aria-label="Back to tables">
            <ArrowLeft size={22} />
          </button>
          <span className="place-badge">{bill.place}</span>
          <div className="bill-meta grow">
            <strong>Bill #{String(bill.number).padStart(4, "0")}</strong>
            <span>
              <span className="avatar sm">{initials(bill.waiter.name)}</span> {bill.waiter.name} · <Clock3 size={14} /> {since(bill.opened_at)}
            </span>
          </div>
        </header>

        {unprinted.map((t) => (
          <div key={t.id} className="not-printed">
            <TriangleAlert size={20} />
            <span className="grow">
              {STATION_TICKET[t.kind]} {t.number} not printed
            </span>
            <button className="btn btn-quiet" onClick={() => setViewing(t.id)}>
              View
            </button>
            <button className="btn btn-orange" onClick={() => reprintTicket(t.id)}>
              <Printer size={18} /> REPRINT
            </button>
          </div>
        ))}

        <div className="bill-lines">
          {rounds.map((round, r) => (
            <div key={round.at}>
              <div className="round-head">
                Round {r + 1} · {new Date(round.at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
                {round.tickets.every((id) => ticketStatus.get(id) === "printed") ? (
                  <span className="ok">
                    <CheckCircle2 size={15} />
                  </span>
                ) : null}
              </div>
              {groupLines(round.lines).map((g) => (
                <button
                  key={g.key}
                  className={`bill-line sent ${g.lines.length ? "" : "voided"}`}
                  onClick={() => canVoid && g.lines.length && bill.status === "open" && setVoiding(g)}
                >
                  <span className="qty">{g.lines.length || g.voided}×</span>
                  <span className="grow">
                    {g.name}
                    {g.note && <span className="line-note">"{g.note}"</span>}
                    {g.voided > 0 && g.lines.length > 0 && <span className="line-note">{g.voided} removed</span>}
                  </span>
                  <span className="amount">{formatKsh(g.unitPrice * g.lines.length)}</span>
                </button>
              ))}
            </div>
          ))}
          {draft.length > 0 && (
            <div className="draft-card">
              <div className="round-head">New round · not sent yet</div>
              {draft.map((l) => (
                <div key={l.key} className="bill-line draft">
                  <button className="step" onClick={() => changeQty(l, -1)} aria-label={`One less ${l.name}`}>
                    {l.quantity === 1 ? <Trash2 size={18} /> : <Minus size={18} />}
                  </button>
                  <span className="qty">{l.quantity}</span>
                  <button className="step" onClick={() => changeQty(l, 1)} aria-label={`One more ${l.name}`}>
                    <Plus size={18} />
                  </button>
                  <button className="grow line-name" onClick={() => setNoteFor(l)}>
                    {l.name}
                    <span className="line-note">{l.note ? `"${l.note}"` : "+ note"}</span>
                  </button>
                  <span className="amount">{formatKsh(l.price * l.quantity)}</span>
                </div>
              ))}
            </div>
          )}
          {!rounds.length && !draft.length && (
            <div className="empty-state">
              <ShoppingBag size={56} />
              Tap items on the left to start the order.
            </div>
          )}
        </div>

        <footer className="bill-foot">
          {(bill.discount > 0 || bill.paid > 0) && (
            <div className="bill-sum">
              <span>Subtotal</span>
              <span>{formatKsh(bill.gross + roundTotal)}</span>
            </div>
          )}
          {bill.discount > 0 && (
            <div className="bill-sum">
              <span>Discount{bill.discount_kind === "percent" ? ` ${bill.discount_value}%` : ""}</span>
              <span>−{formatKsh(bill.discount)}</span>
            </div>
          )}
          {bill.paid > 0 && (
            <div className="bill-sum">
              <span>Paid</span>
              <span>−{formatKsh(bill.paid)}</span>
            </div>
          )}
          <div className="bill-total">
            <span>{bill.paid > 0 ? "TO PAY" : "TOTAL"}</span>
            <span>{formatKsh(bill.total + roundTotal - bill.paid)}</span>
          </div>
          {message && (
            <p className="error-text" role="alert">
              {message.text}
            </p>
          )}
          <div className="bill-buttons">
            <button className="btn btn-quiet" onClick={() => setMore(true)}>
              <Ellipsis size={20} /> More
            </button>
            <button className="btn btn-quiet" onClick={doPrintBill}>
              <ReceiptText size={20} /> BILL
            </button>
          </div>
          <div className="bill-buttons">
            <button className="btn btn-primary send" onClick={send} disabled={!draft.length || busy}>
              <Send size={22} /> SEND
            </button>
            <button className="btn btn-primary pay-btn" onClick={pay}>
              <Wallet size={22} /> PAY
            </button>
          </div>
        </footer>
      </aside>

      {choosing && (
        <Modal title={choosing.name} onClose={() => setChoosing(null)}>
          <div className="choice-list">
            {choosing.options.map((o, i) => (
              <button key={o.id} className="choice" onClick={() => (add(choosing, i), setChoosing(null))}>
                <span>{o.label}</span>
                <span className="pill blue">{formatKsh(o.price)}</span>
              </button>
            ))}
          </div>
        </Modal>
      )}

      {noteFor && (
        <NoteDialog
          line={noteFor}
          presets={menu.note_presets}
          onSave={(note) => {
            setDraft(draft.map((l) => (l.key === noteFor.key ? { ...l, note } : l)));
            setNoteFor(null);
          }}
          onClose={() => setNoteFor(null)}
        />
      )}

      {voiding && (
        <VoidDialog
          session={session}
          bill={bill}
          group={voiding}
          onDone={(updated) => (setBill(updated), setVoiding(null), toast("Item removed from the bill"))}
          onClose={() => setVoiding(null)}
        />
      )}

      {viewing && (
        <ReceiptDialog
          id={viewing}
          title="Printout"
          free={session.permissions.reprint_receipt === "allow"}
          onReprint={() => reprintTicket(viewing)}
          onClose={() => setViewing(null)}
        />
      )}

      {more && (
        <MoreMenu
          session={session}
          bill={bill}
          onChanged={(updated) => (setBill(updated), setMore(false))}
          onOpen={(id) => (setMore(false), onOpen(id))}
          onClosed={() => (setMore(false), onBack())}
          onClose={() => setMore(false)}
        />
      )}
    </main>
  );
}

/** Lines sent together are one round (one SEND), shown in the order they went out. */
function roundsOf(bill: Bill) {
  const rounds = new Map<string, { at: string; lines: Bill["lines"]; tickets: Set<string> }>();
  for (const line of bill.lines) {
    const r = rounds.get(line.sent_at) ?? { at: line.sent_at, lines: [], tickets: new Set<string>() };
    r.lines.push(line);
    r.tickets.add(line.ticket_id);
    rounds.set(line.sent_at, r);
  }
  return [...rounds.values()].map((r) => ({ ...r, tickets: [...r.tickets] }));
}

function NoteDialog({
  line,
  presets,
  onSave,
  onClose,
}: {
  line: DraftLine;
  presets: string[];
  onSave: (note: string | null) => void;
  onClose: () => void;
}) {
  const [note, setNote] = useState(line.note ?? "");
  const toggle = (p: string) => {
    const parts = note ? note.split(", ") : [];
    setNote((parts.includes(p) ? parts.filter((x) => x !== p) : [...parts, p]).join(", "));
  };
  return (
    <Modal title={`Note: ${line.name}`} onClose={onClose}>
      <div className="choice-grid">
        {presets.map((p) => (
          <button key={p} className={`choice ${note.split(", ").includes(p) ? "selected" : ""}`} onClick={() => toggle(p)}>
            {p}
          </button>
        ))}
      </div>
      <input className="text-input" placeholder="Or type a note" value={note} maxLength={120} onChange={(e) => setNote(e.target.value)} />
      {line.quantity > 1 && <p className="muted" style={{ margin: 0 }}>The note applies to all {line.quantity}.</p>}
      <div className="row row-end">
        <button className="btn btn-quiet" onClick={() => onSave(null)}>
          No note
        </button>
        <button className="btn btn-primary" onClick={() => onSave(note.trim() || null)}>
          SAVE NOTE
        </button>
      </div>
    </Modal>
  );
}
