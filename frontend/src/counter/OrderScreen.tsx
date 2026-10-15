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
import { Modal } from "../shared/Modal";
import { formatKsh } from "../shared/money";
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
      setMessage(last.status === "not_printed" ? { text: "Bill NOT printed. Check the printer.", tone: "error" } : { text: "Bill printed.", tone: "ok" });
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
      setBill(await reprint(ticketId));
    } catch (e) {
      fail(e);
    }
  };

  if (!bill) return <main className="screen-center">{message?.text ?? "Loading…"}</main>;

  const groups = groupLines(bill.lines);
  const unprinted = bill.tickets.filter((t) => t.status === "not_printed" && t.kind !== "bill");
  const roundTotal = draftTotal(draft);
  const canVoid = session.permissions.void_item !== "deny";

  return (
    <main className="order">
      <section className="order-menu">
        <div className="category-bar">
          <button className={`cat ${category === FAVOURITES && !search ? "selected" : ""}`} onClick={() => (setCategory(FAVOURITES), setSearch(""))}>
            ★ Fav
          </button>
          {menu.categories.map((c) => (
            <button key={c.id} className={`cat ${category === c.id && !search ? "selected" : ""}`} onClick={() => (setCategory(c.id), setSearch(""))}>
              {c.name}
            </button>
          ))}
          <input className="text-input search" placeholder="🔍 Search" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="item-grid">
          {items.map((item) => (
            <button key={item.id} className={`item-tile ${item.station}`} onClick={() => tapItem(item)}>
              <span className="item-name">{item.name}</span>
              <span className="item-price">
                {item.options.length > 1 ? `from ${formatKsh(Math.min(...item.options.map((o) => o.price)))}` : formatKsh(item.options[0].price)}
              </span>
            </button>
          ))}
          {!items.length && <p className="muted">No items here.</p>}
        </div>
      </section>

      <aside className="bill-panel">
        <header className="bill-head">
          <button className="btn btn-quiet" onClick={back} aria-label="Back to tables">
            ‹ Tables
          </button>
          <div className="grow">
            <div className="bill-place">{bill.place}</div>
            <div className="muted">
              #{String(bill.number).padStart(4, "0")} · {bill.waiter.name}
            </div>
          </div>
        </header>

        {unprinted.map((t) => (
          <div key={t.id} className="not-printed">
            <span className="grow">
              {STATION_TICKET[t.kind]} {t.number} NOT PRINTED
            </span>
            <button className="btn btn-orange" onClick={() => reprintTicket(t.id)}>
              REPRINT
            </button>
          </div>
        ))}

        <div className="bill-lines">
          {groups.map((g) => (
            <button
              key={g.key}
              className={`bill-line sent ${g.lines.length ? "" : "voided"}`}
              onClick={() => canVoid && g.lines.length && bill.status === "open" && setVoiding(g)}
            >
              <span className="qty">{g.lines.length}×</span>
              <span className="grow">
                {g.name}
                {g.note && <span className="line-note">"{g.note}"</span>}
                {g.voided > 0 && <span className="line-note">{g.voided} removed</span>}
              </span>
              <span className="amount">{formatKsh(g.unitPrice * g.lines.length)}</span>
              <span className="tick">✓</span>
            </button>
          ))}
          {draft.length > 0 && <div className="round-divider">── new round ──</div>}
          {draft.map((l) => (
            <div key={l.key} className="bill-line draft">
              <button className="step" onClick={() => changeQty(l, -1)} aria-label={`One less ${l.name}`}>
                −
              </button>
              <span className="qty">{l.quantity}×</span>
              <button className="step" onClick={() => changeQty(l, 1)} aria-label={`One more ${l.name}`}>
                +
              </button>
              <button className="grow line-name" onClick={() => setNoteFor(l)}>
                {l.name}
                <span className="line-note">{l.note ? `"${l.note}"` : "+ note"}</span>
              </button>
              <span className="amount">{formatKsh(l.price * l.quantity)}</span>
            </div>
          ))}
          {!groups.length && !draft.length && <p className="muted">Tap items to start the order.</p>}
        </div>

        <footer className="bill-foot">
          <div className="bill-total">
            <span>TOTAL</span>
            <span>{formatKsh(bill.total + roundTotal)}</span>
          </div>
          {bill.paid > 0 && (
            <div className="row muted bill-paid">
              <span className="grow">Paid {formatKsh(bill.paid)}</span>
              <span>Left {formatKsh(bill.total + roundTotal - bill.paid)}</span>
            </div>
          )}
          {message && (
            <p className={message.tone === "error" ? "error-text" : "ok-text"} role="alert">
              {message.text}
            </p>
          )}
          <div className="bill-buttons">
            <button className="btn btn-quiet" onClick={() => setMore(true)}>
              More
            </button>
            <button className="btn" onClick={doPrintBill}>
              BILL
            </button>
          </div>
          <div className="bill-buttons">
            <button className="btn btn-primary send" onClick={send} disabled={!draft.length || busy}>
              SEND
            </button>
            <button className="btn btn-primary pay-btn" onClick={pay}>
              PAY
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
                <small>{formatKsh(o.price)}</small>
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
          onDone={(updated) => (setBill(updated), setVoiding(null))}
          onClose={() => setVoiding(null)}
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
