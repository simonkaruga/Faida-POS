# Faida POS — Masterplan
**Version 1: Bar & Restaurant edition · single client (quotation AVI-Q-[023])**
Prepared by Avinaya Solutions Ltd · Revision 3 · 15 October 2026

> **How to read this document.** Sections 1–4 cover *what* we are building and why. Sections 5–9 cover *how* it is built, laid out and deployed. Sections 10–14 cover security, schedule, risks and the future. Section 15 is the senior review: one full night at the bar, walked through end to end, to confirm every part fits together. There is no code in this document.

---

## Contents
1. Overview and objectives
2. Target users and roles
3. How the business runs
4. Core features
5. Technical architecture
6. Project structure (frontend and backend folders)
7. Hosting and deployment
8. Conceptual data model
9. Design: touchscreen UI
10. Security
11. Development phases
12. Challenges and solutions
13. Future expansion
14. Open items to confirm with the client
15. Senior review: end-to-end walkthrough and consistency check

---

## 1. Overview and objectives

Faida POS is a simple, reliable point of sale for **one bar and restaurant**. It records every sale, controls stock and cash, and shows the owner her real daily profit, **whether or not the internet is working**.

**Success for the owner**
- Nothing leaves the bar or kitchen without being recorded first (**no slip, no drink**).
- At closing she knows, for each waiter, what they sold, collected, handed over and still owe.
- She sees stock losses in shillings and profit after expenses, and can check them from her phone.
- New staff learn the system in 15–30 minutes.

**Guiding rule:** deliver exactly what the quotation promises, and make every promise work end to end. Nothing extra.

**Out of scope for this delivery**
- **KRA/eTIMS.** The client explicitly asked for it not to be included.
- **Automatic M-Pesa prompts (STK push) and automatic M-Pesa confirmation.** Both can be added later.
- **Hardware.** The client **already owns POS hardware**. Any missing items (e.g. a kitchen printer, UPS, USB drive, or a mini PC if her machine is Android; see 5.3) are her cost, via the hardware partner.

---

## 2. Target users and roles

| Role | Who | Logs in with |
|---|---|---|
| **Owner** | Runs the business, often away | Personal PIN at the counter; email, password and one-time code on her phone |
| **Supervisor** *(optional)* | Trusted senior staff | Personal PIN |
| **Waiter** | Takes orders, serves, **collects payment** | Personal PIN |
| Bar staff and kitchen | Pour and cook against printed slips and tickets | No login |

There is **no separate cashier role**. Waiters collect payment themselves, and the owner or supervisor receives the cash at hand-over.

### Permissions (single source of truth: every other section follows this table)

| Action | Owner | Supervisor | Waiter |
|---|:-:|:-:|:-:|
| Open tables or tabs, add items, send slips, print bills | ✅ | ✅ | ✅ own bills |
| Take payment (cash, M-Pesa, split, tip) | ✅ | ✅ | ✅ own bills |
| See other waiters' bills | ✅ | ✅ | ❌ |
| Move own bill to another table | ✅ | ✅ | ✅ (logged) |
| Hand a bill over to another waiter | ✅ | ✅ | ✅ **receiving waiter enters their PIN** |
| Remove an item already sent (void) | ✅ | ✅ | 🔒 needs Owner or Supervisor PIN |
| Discount, reprint receipt, cancel a paid bill | ✅ | ✅ | 🔒 needs Owner or Supervisor PIN |
| Approve credit for a customer | ✅ | ✅ within the customer's limit | 🔒 request only |
| Mark a bill "unpaid – I am responsible" | — | — | ✅ own bills |
| Receive cash hand-over, close a waiter's shift | ✅ | ✅ | ❌ |
| Force-close a shift (waiter left without closing) | ✅ | ❌ | ❌ |
| Record shortage status (paid back, deducted, forgiven) | ✅ | ❌ | ❌ |
| Receive stock deliveries, do stock takes | ✅ | ✅ | ❌ |
| Record cash pay-outs and expenses | ✅ | ✅ pay-outs only | ❌ |
| See profit, buying prices, stock value, reports | ✅ | ❌ | ❌ |
| Change menu, prices, recipes, staff, PINs, settings | ✅ | ❌ | ❌ |
| Run daily closing | ✅ | ✅ (sees no profit, buying prices or stock values) | ❌ |
| Phone remote view | ✅ | ❌ | ❌ |

---

## 3. How the business runs

1. **Start of shift.** The waiter logs in with their PIN. If the owner gives them change, a float is recorded.
2. **Order.** The waiter takes the order at the table, walks to the counter and enters it.
3. **Send.** Faida prints **drinks on a bar slip** at the counter printer and **food on a kitchen ticket** at the kitchen printer. The bar pours only against a slip.
4. **More rounds** are added to the same open bill.
5. **Bill.** The waiter prints the bill for the customer.
6. **Payment.** The waiter collects cash, or M-Pesa paid to the **business till only** (recorded manually with the **last 4 characters** of the transaction code), or a split of the two. An optional M-Pesa tip can be included.
7. **Receipts.** Faida prints a **customer receipt** and a **counter copy**.
8. **End of shift.** The waiter can't close while they have open bills. Faida calculates the **cash to hand over**. The owner or supervisor counts it, the waiter confirms with their PIN, and both slips print.
9. **Daily closing.** After the last shift, the owner or supervisor runs the closing. The report syncs to the owner's phone whenever internet is available.

**Business day:** a bar trades past midnight, so the business day ends at a **cut-off time set by the owner (default 06:00)**. A sale at 01:30 on Saturday belongs to **Friday's** business day.

---

## 4. Core features

### 4.1 Ordering (bar and restaurant)
- Menu organised in **categories** (Beers, Spirits, Soft drinks, Mains, Snacks…), with a **search** box and a **Favourites** row of the 8–12 fastest-moving items.
- **Open bills by table**, plus **named tabs** for bar regulars (e.g. "Tab – Kamau").
- Food and drinks on **one bill**, added round by round.
- **Spirits** open a small choice: *Single tot / Double / Bottle*.
- **Item notes** for the kitchen ("well done", "no onions") come from quick-pick buttons plus free text.
- **Price is fixed when the item is ordered.** A later price change doesn't alter open bills.
- **Sent items are locked** (marked ✓). Removing one is a void and needs approval.
- **Move bill to another table**, **split a bill** (by items, or several payments), and **merge two bills** belonging to the same waiter.

### 4.2 Printing and routing
- Each menu item is tagged **Bar** or **Kitchen**, and **SEND** routes automatically.
- **Bar slip:** table, waiter, time, slip number, drinks.
- **Kitchen ticket:** table, waiter, time, ticket number, food, notes. Large print.
- **Bill (before payment)** and **Receipt (after payment)**. The receipt prints twice: the **customer copy** and a copy marked **COUNTER COPY**.
- Every receipt says: **"Not a KRA tax invoice."**
- **Printer offline:** the order is still saved and marked **"Not printed"** in orange on the bill. The waiter reprints when the printer is back, and that first reprint needs no approval. Later reprints need approval. The bar keeps the rule *no slip, no drink*.

### 4.3 Payments
- **Cash.** The waiter enters the amount given, and Faida shows the **change** in large figures.
- **M-Pesa (business till only), recorded manually, as the client prefers for busy nights.** No automatic prompts. The customer pays the till as usual, and the waiter taps **M-Pesa** and enters the **last 4 characters** of the code from the customer's message (e.g. `P2QM`). This takes about 2 seconds.
  - **Duplicate check:** if the same last 4 characters were already used in the **last 7 days**, Faida warns *"These 4 characters were used on bill #0131. Check the customer's message"*. It can only continue with **Owner or Supervisor PIN**, because two genuine codes can occasionally share their last 4 characters. Works offline.
  - **Owner setting, "M-Pesa code entry":** *Last 4 characters* (**default, agreed with the client**) · *Full code* (strongest) · *None* (fastest, but M-Pesa can then only be checked as a daily total, not per waiter or per bill). Changing it is logged.
- **Split.** Any mix of cash and M-Pesa, including several people paying one bill. The bill closes only when payments equal the total.
- **Tip (M-Pesa only).** If the customer pays more than the bill to the till as a tip, the waiter records the extra as **Tip**. Tips are **not sales**. At cash-up the tip is taken off the cash to hand over, so the waiter keeps it in cash. Cash tips stay outside Faida.
- **Credit.** See 4.5.

### 4.4 Waiter accountability
- **Personal PINs.** Every action is recorded under the person who did it.
- **Auto-lock** after each SEND, after each payment, and after 30 seconds idle (adjustable).
- **Waiters see only their own bills.** Other waiters' tables show as locked.
- **Hand a bill over:** the receiving waiter enters their PIN to accept it. From then on, the money for that bill belongs to them.
- **Approvals** pop up on the same screen, and the owner or supervisor enters their PIN. They work offline and are **logged with a reason**.
- **Voids and stock.** The approver picks why the item is removed:
  - **"Not prepared"**: the item goes **back to stock**.
  - **"Already prepared / poured"**: recorded as **waste**, so stock stays reduced and the loss is visible.
- **Audit log:** every void, discount, reprint, cancellation, hand-over, approval, price change and force-close is recorded. **Nothing is ever deleted.** Corrections are new, visible entries.

### 4.5 Credit
- **Approved credit (the debt belongs to the customer).** The waiter taps *Request credit*, and the owner or supervisor approves with their PIN. The bill moves to a **named credit customer** (name and phone) with a **credit limit** set by the owner, and leaves the waiter's cash-up.
- **Paying off credit.** When the customer pays later (cash, or M-Pesa with the last 4 characters), the **owner or supervisor** records it against the customer account. It shows in the daily closing as **"Credit collected"**, not in any waiter's cash-up.
- **Debtors list:** who owes, how much and since when, with the oldest first.
- **Walk-outs and unapproved credit.** The waiter marks the bill *"Unpaid – I am responsible"*. The amount is added to their shift's **amount due**.

### 4.6 Waiter cash-up and hand-over
**Screen 1. End my shift.** Blocked while the waiter has open bills. Each open bill shows three options: *Take payment*, *Request credit* or *Mark unpaid – I am responsible*.

**Screen 2. My shift summary.**

| Line | Example |
|---|---|
| Total sales: every bill this waiter finished (paid, credit, or unpaid–responsible) | 18,500 |
| − Paid by M-Pesa (bill amounts only, tips excluded; last-4 codes listed) | 9,200 |
| − Approved credit | 1,200 |
| = Cash due from sales *(includes any unpaid–responsible bills, shown on a line underneath: "of which unpaid – your responsibility: 0")* | 8,100 |
| + Float received at start | 500 |
| − M-Pesa tips (paid to the till, so the waiter takes them in cash) | 200 |
| **= CASH TO HAND OVER** | **8,400** |

*An unpaid–responsible bill isn't subtracted anywhere, so it stays in the cash the waiter owes. That's exactly the rule.*

**Screen 3. Receive cash (Owner or Supervisor PIN).** Count by note (1,000 / 500 / 200 / 100 / 50 / coins) or type a total. Faida shows **Balanced**, **Short** or **Over**. The receiver can add a note and view each M-Pesa payment (bill, amount, last 4 characters) and tick it off against the till messages or statement.

**Screen 4. Sign-off.** The waiter enters their PIN to **agree**, or **disagree with a note**. Two slips print, one for the waiter and one for the owner. The shift then closes.

**Rules**
- Faida calculates the amount due. **No one types it.**
- After confirmation the hand-over **can't be edited**, only corrected with a new visible entry.
- **Overs are recorded too.** They can reveal sales that weren't recorded.
- **Force-close (Owner only):** if a waiter leaves without closing, the owner closes their shift. Their open bills are marked *unpaid – waiter responsible* unless she handles them another way. She records the cash actually received, which may be zero, so the full amount still owed shows as that waiter's shortage. The waiter's sign-off is recorded as *"not present"*. It's flagged in the audit log.
- **Shortage status (Owner only):** each shortage is later marked **Paid back**, **Deducted** or **Forgiven**. Faida never deducts salaries itself. Any deduction is her decision under her house rules and employment law.
- **Pattern alert:** "Ann short 3 times this month – KSh 1,450".

### 4.7 Bar stock
- **Stock units:**
  - **Spirits** are tracked in millilitres.
  - **Beer and soft drinks** are tracked in bottles.
- **Sell options:**
  - *Single tot*, *Double* and *Bottle* are linked to the same stock item.
  - The **tot size** is set by the owner.
  - An item can be set to *bottle only*.
- **Bottle sizes** of the same brand (quarter, half, full) are **separate stock items**.
- **Deliveries:**
  - Entered by crate or carton and converted to bottles (e.g. 1 crate = 24).
  - Each delivery records the supplier and buying price.
- **Stock take:**
  - Staff count sealed bottles, plus the open bottle in tenths.
  - Faida gives the **variance in units and shillings**, e.g. *"Missing 0.6 bottle ≈ 18 tots ≈ KSh 2,700"*.
- **Never blocks a sale.** If system stock reaches zero, the sale goes through and the item is **flagged**. Stock data can be wrong, but a customer should never be refused because of the system.
- **Low-stock alerts** at a reorder level set per item.
- **Waste/breakage** is recorded with a reason (e.g. a broken bottle). It needs Owner or Supervisor PIN.

### 4.8 Kitchen stock
- **Recipes:** each dish lists ingredients and quantities, and selling the dish takes them off stock.
- Deliveries, stock takes, waste and variance work exactly as for the bar.

### 4.9 Owner tools and reports
- **Expenses:** rent, power, salaries and other costs, by category.
- **Cash pay-outs:** cash taken from the day's takings, e.g. to buy ice. These are recorded at the counter and reduce the cash expected at daily closing.
- **Profit:** Sales − cost of goods sold (from buying prices) − expenses = **real profit**.
- **Daily closing:**
  - Sales (cash, M-Pesa, credit)
  - Credit collected
  - Pay-outs
  - The waiter cash-up table
  - Shortages and overs
  - Voids and discounts (requested by, approved by)
  - Unpaid bills
  - Stock variance
  - Low stock
- **Reports** for daily, weekly, monthly or a custom period:
  - Sales by item, by category, by waiter and by hour
  - Best and worst sellers
  - Stock levels and values
  - Variance history
  - Debtors
  - Expenses
  - Profit
  - Shortage history per waiter

### 4.10 Owner's phone view (read-only in Version 1)
- **Today at a glance:** sales, cash, M-Pesa, credit, shortages, voids, low stock.
- **Detail views:** the daily closing report, waiters, stock variance, profit and debtors.
- Shows **"Last updated HH:MM"** so she always knows how fresh the data is.

---

## 5. Technical architecture

### 5.1 Offline-first with cloud sync

```
 BAR PREMISES (works with no internet)                    CLOUD
 ┌───────────────────────────────────────────┐
 │ Counter touchscreen PC                    │
 │  ├─ Faida backend (local mode)            │   sync     ┌──────────────────────┐
 │  ├─ Local PostgreSQL database             │ ─────────▶ │ Faida backend        │
 │  ├─ Faida frontend (counter screens)      │ (when      │   (cloud mode)       │
 │  └─ Nightly backup → USB drive            │  online)   │ Cloud PostgreSQL     │
 │        │                    │             │            │ Owner phone view     │
 │  Counter printer (USB)  Kitchen printer   │            └──────────┬───────────┘
 │  + cash drawer          (local network)   │                       │
 └───────────────────────────────────────────┘           Owner's phone (browser)
```

**Rules that keep it simple and safe**
1. **The counter is the source of truth.** Everything is decided and saved locally first.
2. **One-way sync in Version 1** (counter → cloud). Menu, prices and staff are changed only at the counter, so the two copies can never disagree.
3. **Sync is a queue.** Every saved change is queued and uploaded in order when internet is available. Uploads are **safe to repeat**, so a dropped connection never creates duplicates.
4. **Every record has a globally unique ID** created on the counter, so records made offline never clash with others in the shared cloud.
5. **Every record carries the business ID**, because one cloud serves all Faida clients (see 7.2).
6. **Human-friendly numbers** for bills, slips and receipts (e.g. #0142) are separate from the hidden unique IDs.
7. **Time.** The counter clock is the record time. If the cloud sees the counter clock is off by more than 5 minutes, it raises a warning.

### 5.2 Stack (uses skills Kelvin already has)

| Part | Choice | Why |
|---|---|---|
| Frontend | **React + TypeScript**, touch-first web app | One codebase serves the counter screens and the owner's phone view |
| Backend | **Python + FastAPI** | Same code runs in **local mode** (counter) and **cloud mode** (server) |
| Database | **PostgreSQL** on both counter and cloud | Same database engine everywhere means the same behaviour, the same migrations and no surprises when syncing |
| Printing | Built into the backend's **printing module**, talking to 80 mm thermal printers using the standard ESC/POS printer language | No extra helper program. Works offline |
| Counter display | The frontend opened **full-screen (kiosk mode)** at start-up | Staff can't wander off into the desktop |

Alternatives considered: a desktop-app framework, and a cloud-only app with offline caching. Both were rejected. The first means a new toolset; the second is fragile offline.

### 5.3 Hardware rule (important)
- **The client already owns POS hardware. Its brand and model must be confirmed before Phase 1 ends** (open item 9).
- The device that runs the **local backend and database must be a Windows or Linux PC**. A **15.6″ touchscreen all-in-one POS PC** is ideal, and a laptop is acceptable.
- **If her machine is Windows:** Faida installs directly on it. ✅
- **If her machine is Android** (common in Kenya, e.g. 15.6″ dual-screen units): it **can't run the Faida backend**. The plan becomes a small **mini PC** (back office, on the UPS) running the backend and database. Her Android machine opens the Faida counter screens over the local network as the touch screen. The design and code are the same either way; only the install changes.
- **2 × 80 mm thermal printers:** counter (USB, with the cash drawer attached) and kitchen (**network** model).
- **UPS** for the PC and the router. **One USB drive** for nightly backups.
- **Design screen size:** 1366×768 and 1920×1080 landscape. Owner phone in portrait.

---

## 6. Project structure (frontend and backend folders)

One project, two main folders, so each part can be built, tested and deployed separately. The names below are the agreed layout. There is no code here, only what each folder is for.

```
faida/
├── frontend/                     ← everything users see (React + TypeScript)
│   ├── src/
│   │   ├── counter/              ← touchscreen app: PIN login, tables, order,
│   │   │                            payment, end shift, approvals
│   │   ├── owner-area/           ← counter screens behind owner PIN: stock,
│   │   │                            menu, staff, expenses, closing, settings
│   │   ├── owner-phone/          ← read-only remote view (cloud)
│   │   ├── shared/               ← design system: buttons, keypad, money
│   │   │                            display, colours, fonts, icons
│   │   └── services/             ← talks to the backend; offline status
│   ├── public/                   ← static files
│   └── tests/
│
├── backend/                      ← all rules, money logic and data (Python + FastAPI)
│   ├── app/
│   │   ├── auth/                 ← PINs, roles, permissions, approvals, auto-lock
│   │   ├── staff/
│   │   ├── menu/                 ← categories, items, sell options, recipes
│   │   ├── floor/                ← tables, tabs, bills, bill lines, hand-overs
│   │   ├── payments/             ← cash, M-Pesa codes, splits, tips
│   │   ├── shifts/               ← floats, cash-up, hand-over, shortages
│   │   ├── credit/               ← credit customers, limits, collections
│   │   ├── stock/                ← items, deliveries, stock takes, waste, variance
│   │   ├── expenses/             ← expenses, pay-outs
│   │   ├── reports/              ← daily closing, all reports, profit
│   │   ├── printing/             ← routing, slip and receipt layouts, printer status
│   │   ├── audit/                ← permanent audit log
│   │   ├── sync/                 ← local: upload queue · cloud: receive and check
│   │   └── settings/             ← business settings, business-day cut-off, mode
│   ├── migrations/               ← database changes, applied the same way locally and in cloud
│   └── tests/                    ← money and stock rules tested first and hardest
│
├── deploy/
│   ├── local/                    ← counter installer: services, auto-start,
│   │                                kiosk mode, nightly backup, update/rollback
│   └── cloud/                    ← cloud server setup, backups, health monitoring
│
└── docs/
    ├── masterplan.md             ← this document
    ├── install-checklist.md      ← on-site steps (see 7.1)
    └── house-rules.md            ← one-page staff rules the owner signs
```

**Why it's arranged this way**
- **Backend folders follow the business.** Each folder matches one area of the masterplan (sections 4.1–4.10), so a bug report like "cash-up is wrong" points to one place.
- **One backend, two modes.** `settings` decides *local* or *cloud*. Local mode prints and queues sync; cloud mode receives sync and serves the phone view.
- **One frontend build, used in two places.** The counter loads `counter/` and `owner-area/` from the local backend. The cloud serves only `owner-phone/`.

---

## 7. Hosting and deployment

### 7.1 Counter (on-site install)
1. Check the hardware against 5.3.
2. Install PostgreSQL, the Faida backend in local mode, and the frontend. Set them to **start automatically** and open **full-screen**.
3. Connect and test the printers: a food item prints in the kitchen, a drink at the bar, and the cash drawer opens on a cash payment.
4. Turn on **disk encryption**, the **UPS**, and **nightly backup to USB**.
5. Load the business data:
   - Menu, prices, tot size, recipes
   - Tables, staff and PINs, credit customers
   - Business-day cut-off
6. Enter the **opening stock count** with the owner.
7. **Link to the cloud.** The counter registers with the Faida cloud under the business's ID, and the first sync is confirmed.
8. Train staff (15–30 minutes each), sign the house rules, and **demo before handover**.

**Updates after handover**
- Triggered remotely by Avinaya, **after closing hours only**.
- Every update runs **backup → update → automatic check**, with **one-step rollback** if the check fails.
- The cloud always accepts uploads from the **current and previous** counter version, so an un-updated counter keeps syncing.

### 7.2 Cloud (shared Faida cloud)
- **One shared cloud for all Faida clients.** Every record is separated by business ID, and each owner can only ever see her own business.
- **Contents:** backend in cloud mode, PostgreSQL, the owner phone view, and daily encrypted backups.
- **Health monitor:** Avinaya is alerted if a counter hasn't synced for **24 hours**, or if a backup fails.
- **Domain:** a Faida domain (e.g. a .co.ke) for the phone view, plus a support WhatsApp number.

**Cost reality**
- A small server plus backups costs roughly **USD 8–15 a month**, about **KSh 12,000–23,000 a year**.
- With **one** client at KSh 7,400 a year, hosting runs at a small loss.
- From about **3 clients**, it pays for itself.
- Year 1 is the platform investment. **Never one server per client.**

### 7.3 Who pays for what

| Item | Where | Paid by |
|---|---|---|
| Software, installation, training, year-1 hosting, 3 months of support | Counter and cloud | KSh 80,000 (50% before install, 50% after demo) |
| Hosting renewal | Cloud | KSh 7,400 a year from year 2 |
| Support after 3 months | Remote or on-site | Per call: **[rate to be set]** |
| POS machine (already owned), any missing printer, drawer, UPS, USB, mini PC if needed | Premises | Client, via hardware partner |
| Domain, shared cloud server | Avinaya | Avinaya |

---

## 8. Conceptual data model

Every record has: a **unique ID**, a **business ID**, **created by** (staff), **created at**, and a **sync status**.

| Area | Records | Key relationships and rules |
|---|---|---|
| **Business** | Business · Settings (tot size, business-day cut-off, auto-lock time, receipt text) | One counter per business in Version 1 |
| **People** | Staff (name, role, PIN stored securely, active or left) · Credit customer (name, phone, limit) | A staff member who leaves is deactivated, never deleted |
| **Menu** | Category · Menu item (Bar or Kitchen tag) · Sell option (tot, double, bottle, plate) · Recipe line | A sell option or recipe line links what is sold to the stock it uses, and how much |
| **Stock** | Stock item (base unit, buying price, reorder level) · Supplier · Delivery · Stock take · **Stock movement** | **Every** stock change is a movement: sale, delivery, waste, stock-take adjustment |
| **Floor** | Table · Bill (open, paid, on credit, unpaid–waiter responsible, cancelled) · Bill line (price fixed at order time, sent ✓) · Printed ticket (printed or not printed) · Bill hand-over (from, to, both PINs) | Each bill belongs to exactly one waiter at a time |
| **Money** | Payment (cash or M-Pesa, amount, **M-Pesa reference = last 4 characters**, tip) · Credit collection · Expense · Cash pay-out | A repeated reference within 7 days needs approval (logged). The setting can store the full code instead |
| **Shifts** | Shift (waiter, start, end, float) · Hand-over (expected, counted by note, received, short or over, receiver, waiter agrees or disagrees, note) · Shortage status (paid back, deducted, forgiven) · Daily closing (business day) | A shift belongs to one business day |
| **Control** | Approval (what, requested by, approved by, reason) · Audit entry | Neither can be edited or deleted |
| **Sync** | Sync queue entry · Device registration · Software version | Queue entries are safe to resend |

---

## 9. Design: touchscreen UI

### 9.1 What we learned from the market leaders

| Market practice | Seen in | Faida decision |
|---|---|---|
| **Table-first home screen.** Restaurant users ask for the floor plan as the default home screen, and complain when it takes extra taps to reach | Square for Restaurants (community feedback) | **Tables is the waiter's home screen** |
| **Menu drill-down + search** (menus → groups → items) with a search bar above the items | Toast | Categories + search + Favourites row |
| **Check always visible**, with **Send / Pay** fixed at the bottom of the check and rare actions in an overflow menu | Toast | Bill panel always on the right. SEND and PAY fixed at the bottom. Rare actions under "More" |
| **Dark and light modes** on ordering screens | Toast | Dark by default at the counter (dim bar), light option |
| **Big touch targets**: 44 pt (Apple), 48 dp (Material), 44 px (WCAG AAA). Restaurant POS guidance suggests **56 px minimum, 64 px preferred** | Apple, Google, WCAG, POS UI standards | **Item tiles 72 px tall, all buttons ≥ 56 px, keypad keys ≥ 72 px** |
| **Common POS hardware: 15.6″ landscape touch at 1920×1080** | Sunmi T2s and similar | Design for 1366×768 and 1920×1080 landscape |

### 9.2 Design rules
1. **Three taps to send a round:** table → items → SEND.
2. **One job per screen.** Ordering, paying and cash-up are separate, focused screens.
3. **Thumb-sized everything:** buttons at least 56 px, primary actions 72 px, with gaps of at least 8 px between tappable things.
4. **Money is unmistakable.** Totals are the largest text on the screen, and change due and cash to hand over are shown in very large figures.
5. **Colour has meaning, used consistently:**

| Colour | Meaning |
|---|---|
| **Navy** | Structure, headers, primary buttons |
| **Blue** | Selected items, your open tables, SEND |
| **Orange** | Needs attention: open bills, not printed, low stock, short |
| **Yellow** | Approvals and credit |
| **Green / red** | Only for results: balanced or paid / short or rejected |

6. **Roles change what's shown, not how it looks.** One app with the same layout everywhere.
7. **Always show status:** a 🟢/🟡 dot for online/offline and printer status in the top bar.
8. **Plain English verbs:** SEND, BILL, PAY, END MY SHIFT.
9. **No hidden gestures.** No swipes or long-presses for important actions; everything is a visible button.
10. **Brand:** Avinaya colours, the business name in the header and on receipts, **no Avinaya logo**.

### 9.3 Counter screen layout (landscape)

```
┌─────────────────────────────────────────────────────────────────┐
│ TOP BAR: Business name · Jane ▾ · 🟢 Online · 🖨 OK · 21:58     │
├───────────────────────────────────────────┬─────────────────────┤
│ CATEGORIES  [Fav][Beers][Spirits][Soft]   │ BILL PANEL          │
│             [Mains][Snacks]  [🔍 Search]  │ Table 2 · Jane      │
├───────────────────────────────────────────┤ 2× Tusker    600 ✓  │
│ ITEM TILES (72 px tall, 4–5 per row)      │ 1× Chips     250 ✓  │
│ [Tusker 300 ] [Guinness 320] [WhiteCap ]  │ ── new round ──     │
│ [Balozi 280 ] [Pilsner 280 ] [Smirn.Ice]  │ 2× Tusker    600    │
│ [Coke 100   ] [Water 80    ] [Soda 100 ]  │ 1× Chicken   650    │
│                                           │   "well done"       │
│                                           ├─────────────────────┤
│                                           │ TOTAL     2,100     │
│                                           │ [More] [BILL]       │
│                                           │ [   SEND   ][ PAY ] │
└───────────────────────────────────────────┴─────────────────────┘
```

### 9.4 Screen list

| Screen | Who | Purpose | Key elements |
|---|---|---|---|
| PIN login | All | Who is working | Large keypad, business name, online/printer status |
| **Tables (home)** | Waiter+ | See and open tables | Grid of tables: free / **mine (blue, amount)** / other (grey, locked) · + New tab · End my shift |
| **Order** | Waiter+ | Add items, send | Layout 9.3 · spirits choice pop-up · notes · More: move table, hand over, split, merge |
| **Pay** | Waiter+ | Take payment | Cash / M-Pesa / Split · amount · **4-character M-Pesa box with large letter/number keypad** · tip · change shown large · Request credit |
| Approval pop-up | Owner/Supervisor | Approve sensitive actions | What, who, reason, PIN, Approve/Reject |
| **End my shift** (4 steps) | Waiter + receiver | Cash-up | As in 4.6 |
| Owner area home | Owner (Supervisor: some) | Management | Tiles: Hand-overs · Closing · Stock · Menu · Staff · Credit · Expenses · Reports · Settings |
| Stock: delivery / stock take / waste | Owner/Supervisor | Keep stock true | Large number pads, crate→bottle helper, open-bottle tenths slider |
| Daily closing | Owner/Supervisor | End the business day | Summary + waiter table + alerts → Close day |
| **Phone: Today** | Owner | Remote view | Big numbers first, orange alerts, "Last updated" |

### 9.5 Printed layouts
- **Bar slip and kitchen ticket:** table and waiter **large** at the top, slip/ticket number, time, items, notes. The kitchen ticket uses extra-large item text.
- **Bill:** business name, table, waiter, items, total, payment instructions with the M-Pesa till number.
- **Receipt:** business name, receipt number, table, waiter, items, total, payment method and M-Pesa reference (last 4), tip if any, "Not a KRA tax invoice", thank-you line. The **counter copy** is the same receipt marked COUNTER COPY.
- **Hand-over slip (×2):** waiter, shift times, the full cash-up table, received, short or over, receiver, agree or disagree.

---

## 10. Security

- **PINs** are stored securely, never in plain text. Repeated wrong PINs lock that user for a short time. The owner resets PINs.
- **Permissions are enforced by the backend**, not just hidden buttons (section 2 is the single source of truth).
- **Approvals with reasons, and an audit log that can't be edited or deleted.**
- **Auto-lock** after each send, after each payment, and when idle.
- **Owner phone login:** email, strong password and a **one-time code**. Phone view is read-only in Version 1.
- **Shared cloud separation:** every request is checked against the logged-in owner's business ID.
- **Encrypted** connection to the cloud, encrypted cloud backups, and **disk encryption** on the counter PC.
- **Support access** by Avinaya happens only with the owner's permission, and is logged.
- **Data ownership:** the data belongs to the client. This is stated in the handover documents.
- **House rules** (one page, signed): personal PINs never shared, ask before giving credit, *no slip no drink*, shortages are recorded.

---

## 11. Development phases

The quotation promises about **10–14 working days**. The order below makes sure the most important parts are finished first. **Money and stock rules get automatic tests before any screen is polished.**

| Phase | Days | Deliverables | Done when… |
|---|---|---|---|
| **0. Collect** | Before day 1 | Menu and prices, tot size, recipes, tables, staff, credit customers, cut-off time, printer purchase, house rules. **First 50% (KSh 40,000) received.** | All client data is in hand |
| **1. Foundation** | 1–2 | Project folders (section 6), local and cloud modes, database, staff and PIN login, roles and permissions, audit log | A waiter can log in and is limited to their own permissions |
| **2. Selling and printing** | 3–5 | Menu, tables and tabs, order screen, SEND routing, bill, payments (cash, M-Pesa last-4 entry + duplicate warning, split, tip), two receipts, approvals, hand bill over, move table | A full round, from order to two receipts, works offline |
| **3. Cash control** | 6–7 | Shifts, float, credit (both paths), end my shift, receive cash, sign-off, force-close, shortage status, pay-outs | The cash-up maths passes every test case |
| **4. Stock** | 8–9 | Stock items, sell options, recipes, deliveries, waste, stock take, variance in money, alerts | Selling a tot, a bottle and a dish all reduce stock correctly |
| **5. Owner and cloud** | 10–11 | Expenses, profit, daily closing, reports, sync queue, cloud receive, phone view, health monitor, backups | The phone shows correct numbers after a 24-hour offline test |
| **6. Install and hand over** | 12–14 | Install (7.1), opening stock, training, **2–3 day soft launch** alongside her current method, demo, **second 50%**, support period begins | The owner signs acceptance |

---

## 12. Challenges and solutions

| Challenge | Solution |
|---|---|
| Tight timeline | Scope locked to the quotation. Phase order. Client data collected before day 1 |
| Wrong opening stock, so wrong variance | A careful opening count with the owner. First week treated as calibration |
| Peak-hour queue at one counter | Three-tap rounds, fast PIN switching, Favourites row. Waiter phones are a planned upgrade |
| Power cuts | UPS. Every action saved immediately |
| Printer failure | Order saved and marked *Not printed*. First reprint free, later reprints approved |
| Long internet outage | No effect on selling. Phone shows "Last updated…". Health alert to Avinaya after 24 hours |
| Fake or reused M-Pesa payments | Last 4 characters required, repeats within 7 days need approval, every M-Pesa payment listed per waiter at cash-up for ticking off against the till |
| PIN sharing | Auto-lock, house rules, accountability per PIN |
| Disputes over shortages | Faida calculates the amount, two PINs confirm, two slips print, disagreements recorded |
| Counter PC failure or theft | Nightly USB backup + cloud copy. A restore procedure is in the deployment files |
| Her existing POS machine is Android | Mini PC runs the backend, her machine is the touch screen (5.3). Confirm the model early |
| Tax compliance | Out of scope by client request. "Not a KRA tax invoice" on receipts. The quote states this |
| Support load (late-night calls) | Support hours and response times defined. Calls logged and billed after 3 months |
| Hosting margin | Shared cloud. Break-even at about 3 clients |

---

## 13. Future expansion
- **Automatic M-Pesa confirmation (C2B)**, then STK push.
- **Waiter phones** ordering at the table over the local network.
- **Kitchen display screen** instead of paper tickets.
- **WhatsApp/SMS daily closing** to the owner.
- **Two-way sync:** owner edits menu and prices from her phone.
- **KRA eTIMS**, only for clients who request it. The data needed is already recorded.
- **Avi assistant** for owner questions.
- **Multiple counters and branches, other sectors.** The foundation (business ID, unique IDs, sync queue) is already built for this.
- Happy hour, loyalty, tip pooling, bottle weighing.

---

## 14. Open items to confirm with the client
1. Tot size, and which spirits are sold by the tot.
2. Supervisor: yes or no, and who.
3. Waiter floats: yes or no, and the amount.
4. Credit customers and their limits.
5. House rules for shortages.
6. M-Pesa **till** number for bills and receipts.
7. Number of tables and their names.
8. Business-day cut-off time (default 06:00).
9. **Brand and model of her existing POS machine** (Windows or Android?), built-in printer?, and which printers she has for counter and kitchen (see 5.3). **Most urgent.**
10. Avinaya's per-call support rate after 3 months.

---

## 15. Senior review: end-to-end walkthrough and consistency check

### 15.1 One Friday night, start to finish

| Time | What happens | Sections | Check |
|---|---|---|---|
| 17:55 | Jane logs in, and the owner gives her a KSh 500 float | 4.4, 4.6 | Float recorded in Jane's shift ✓ |
| 18:10 | Table 2 orders 2 Tusker + chicken & chips. Jane taps T2 → items → SEND | 4.1, 4.2 | Beer slip prints at the bar, chicken ticket in the kitchen. 2 bottles off beer stock, recipe ingredients off kitchen stock ✓ |
| 18:40 | Internet drops | 5.1 | Top bar shows 🟡. Selling and printing continue. Sync queue grows ✓ |
| 19:05 | Second round: 2 single tots of whisky | 4.1, 4.7 | Tot choice pop-up. 2 × tot size in ml off the bottle. Slip prints ✓ |
| 19:20 | The customer changes their mind on 1 tot, already sent but not yet poured | 4.4 | Void needs a PIN. Supervisor approves with reason "Not prepared". Logged, and the tot goes back to stock ✓ (if it had been poured, "Already poured" records it as waste) |
| 20:30 | Bill: 2,100 paid M-Pesa 2,300 (200 tip), Jane enters last 4 `P2QM` | 4.3 | Not used in the last 7 days ✓. Bill closed. Tip recorded separately, not as a sale ✓. Two receipts print ✓ |
| 21:00 | The kitchen printer jams on table 6's food | 4.2 | Ticket marked *Not printed* (orange). Fixed, then reprinted with no approval needed ✓ |
| 21:30 | Mr. Otieno asks to pay at month end | 4.5 | Jane requests credit, the owner approves within his limit, and the bill moves to his account, out of Jane's cash-up ✓ |
| 22:00 | Jane hands table 9 to Peter | 4.4 | Peter enters his PIN, and the bill and its money now belong to Peter ✓ |
| 22:10 | The owner takes KSh 300 from takings to buy ice | 4.9 | Pay-out recorded. The expected cash at closing is reduced ✓ |
| 23:40 | Jane ends her shift, with no open bills left | 4.6 | Summary shows cash to hand over = cash sales + float − tip ✓. Owner counts 50 short. Jane agrees with her PIN, and two slips print ✓ |
| 00:30 | Ann leaves without ending her shift | 4.6 | The owner force-closes it. Open bills become *unpaid – waiter responsible*. Cash received is recorded as 0, so Ann's full amount due shows as her shortage. Sign-off "not present". Flagged ✓ |
| 01:15 | Last sale | 3 | Belongs to **Friday** (cut-off 06:00) ✓ |
| 01:30 | Daily closing | 4.9 | Sales, credit, pay-outs, the waiter table, shortages, voids requested and approved, variance. Day closed ✓ |
| 07:00 | Internet back | 5.1 | Queue uploads in order. Repeats are ignored. The phone shows Friday with "Last updated 07:01" ✓ |
| Monday | Stock take | 4.7 | Whisky variance shown in tots and KSh ✓ |

### 15.2 Consistency fixes made in this revision

| # | Issue found in Revision 1 or our discussion | Resolution now applied |
|---|---|---|
| 1 | A "Cashier" role appeared in early discussion, but waiters collect payment | **No cashier role.** Owner, Supervisor, Waiter only (section 2) |
| 2 | Moving a bill to another waiter "needs approval" vs the market practice of the receiver's PIN | **Receiving waiter's PIN**, logged. Owner approval not required (2, 4.4) |
| 3 | A separate "print helper" vs printing inside the backend | **Printing module inside the backend**. No extra program (5.2, 6) |
| 4 | Local database type was unspecified | **PostgreSQL on both** counter and cloud (5.2) |
| 5 | Records created offline could clash in a shared cloud | **Unique IDs + business ID** on every record (5.1, 8) |
| 6 | Bars trade past midnight, so dates were ambiguous | **Business-day cut-off** (3, 8) |
| 7 | Tips could appear as overs at cash-up | **Tip line** subtracted from cash to hand over. Not a sale (4.3, 4.6) |
| 8 | Credit paid later: whose cash-up? | Recorded by **Owner or Supervisor** as *Credit collected* in daily closing, never in a waiter's (4.5) |
| 9 | Cash taken from takings for purchases was unaccounted | **Cash pay-outs** reduce expected cash at closing (4.9) |
| 10 | Stock at zero could block a sale | **Never block, flag instead** (4.7) |
| 11 | Price changes could alter open bills | **Price fixed at order time** (4.1, 8) |
| 12 | Unclear what happens when a printer is offline | **Not printed** flag, free first reprint (4.2) |
| 13 | Android POS terminals can't run the backend, and the client already owns a POS machine | **Confirm her model.** If Android, add a mini PC as the backend host (5.3, 14) |
| 14 | An un-updated counter could stop syncing after a cloud update | Cloud accepts **current + previous** version (7.1) |
| 15 | Hosting cost per client exceeds the renewal fee | **Shared cloud**, break-even at about 3 clients (7.2) |
| 16 | Cash-up table counted unpaid–responsible bills twice, and the M-Pesa line could include tips | Total sales includes every finished bill. **M-Pesa line = bill amounts only.** Unpaid–responsible stays inside cash due (4.6) |
| 17 | Voiding a drink already poured would wrongly return it to stock | Void reason **"Not prepared" → back to stock, "Already poured" → waste** (4.4) |
| 18 | A supervisor running daily closing could see profit | Supervisor's closing view **hides profit, buying prices and stock values** (2) |
| 19 | Force-close didn't say what happens to cash the waiter took home | Owner records **cash received (may be 0)**, the rest becomes that waiter's shortage, sign-off "not present" (4.6) |
| 20 | Client wants manual M-Pesa that's quick on busy nights | **Last 4 characters** of the code (default), repeats within 7 days need approval, owner setting to change (4.3, 8) |
| 21 | The cash drawer opened on every cash payment, but waiters hold their own cash until hand-over | **Waiters keep their own cash.** The drawer holds the owner's or supervisor's money and opens for hand-overs, floats, pay-outs and cash credit payments (decided 15 Oct 2026) |
| 22 | Pay-outs and cash credit payments had no cash to come from or go to | A **counter cash box**: hand-overs in, floats and pay-outs out, cash credit payments in. Its expected balance is checked at closing |
| 23 | How discounts work was not defined | **A fixed amount or a percentage of the whole bill**, approved by Owner or Supervisor PIN for waiters. Sales and the waiter's cash due are net of it |
| 24 | What cancelling a paid bill does was not defined | **Full reversal**: its payments and sales are removed, and the approver picks *not prepared → back to stock* or *already served → waste*. Only while the shift that finished the bill is still open; after hand-over a refund is a pay-out |

### 15.3 Final checks

| Check | Result |
|---|---|
| Every quotation line is covered by a feature | ✅ (see 15.4) |
| Every role action in section 2 has a screen in 9.4 | ✅ |
| Every money movement ends in a cash-up or the daily closing: sale, tip, credit, credit collected, pay-out, float, shortage | ✅ |
| Every stock movement is recorded: sale, void return, delivery, waste, stock take | ✅ |
| Everything at the counter works offline | ✅ (only the phone view and backups need internet) |
| Nothing out of scope (KRA, STK) is required by any feature | ✅ |
| Every backend folder maps to a feature section | ✅ (section 6) |

### 15.4 Quotation → masterplan traceability

| Quotation promise | Where delivered |
|---|---|
| See your money daily | 4.9 Daily closing · 4.10 Phone view |
| Stop losing stock | 4.7, 4.8 · *no slip, no drink* (4.2) |
| Cash and M-Pesa together | 4.3 Payments · 4.6 Cash-up |
| Know who sold what (each cashier has a login) | 2 Roles · 4.4 PINs and audit (waiters take the cashier role) |
| See your real profit | 4.9 Expenses and profit |
| Easy for your staff, 15–30 min training | 9 Design · 7.1 step 8 |
| Bar: drinks list, cash/M-Pesa, change, stock drops | 4.1, 4.3, 4.7 |
| Restaurant: menu, orders by table, one bill, ingredient stock | 4.1, 4.8 |
| Owner: reports, expenses/profit, logins, daily closing | 4.9, 2 |
| Included: software, installation, hosting, training, demo | 7.1, 7.2, 11 (Phase 6) |
| Not included: eTIMS, STK, equipment | 1 (out of scope), 5.3, 13 |
| 3 months of support, hosting renewal KSh 7,400 a year | 7.3 |
| 50% before installation, 50% after | 11 (Phases 0 and 6) |

---

### Sources consulted for the design and market decisions
- Toast — ordering screen layout: https://support.toasttab.com/en/article/New-POS-Experience-Ordering-Screens
- Toast — glossary (cash in hand, shift review): https://doc.toasttab.com/doc/platformguide/adminGlossary.html
- Square community — floor plan as home screen: https://community.squareup.com/t5/Square-for-Restaurants/Floor-plan-as-Home-Screen/m-p/755037
- Square — close-of-day procedures: https://squareup.com/help/article/6566
- TouchBistro — ending a server's shift: https://cdn.touchbistro.com/help/articles/server-guide-ending-your-shift
- Lightspeed — clocking out and open orders: https://k-series-support.lightspeedhq.com/hc/articles/360050309174
- Touch target sizes (Apple, Material, WCAG): https://specification.website/spec/accessibility/touch-target-size/
- Restaurant POS UI standard (56–64 px targets): https://skills.cat/skills/peterbamuhigire/skills-web-dev/pos-restaurant-ui-standard
- Sunmi T2s 15.6″ Android POS specs: https://www.yeppon.it/products/sunmi-sistema-pos-t2s-1325992
- SimbaPOS features: https://www.simbapos.co.ke/restaurant-and-bar-point-of-sale-pos-software-in-kenya/
- PaybillKE — M-Pesa for restaurants: https://paybillke.com/guides/mpesa-for-restaurants-2026
- Veira — bar POS in Kenya: https://veirahq.com/blog/top-5-pos-systems-bars-kenya/
- Moneta — Kenya restaurant POS: https://moneta-pay.app/kenya-restaurant-pos
- Hetzner 2026 price changes: https://findstack.com/resources/hetzner-price-increase-2026
- DigitalOcean pricing: https://costbench.com/software/cloud-infrastructure/digitalocean
- Kenya Employment Act s.19: https://sheriaplex.com/kenya-acts/1433-section-19-deduction-of-wages
