"""Phase 5: expenses, profit, daily closing and reports (masterplan 4.9)."""

import pytest
from conftest import login

SAM, JANE = "8642", "1357"


@pytest.fixture
def people(add_staff):
    add_staff("Sam", "supervisor", SAM)
    add_staff("Jane", "waiter", JANE)


@pytest.fixture
def opts(client, owner, menu):
    out = {}
    for cat in client.get("/api/menu", headers=owner).json()["categories"]:
        for item in cat["items"]:
            for o in item["options"]:
                out[f"{item['name']} - {o['label']}" if o["label"] else item["name"]] = o["id"]
    return out


def stock_id(client, headers, name):
    return next(s["id"] for s in client.get("/api/stock", headers=headers).json() if s["name"] == name)


def sell_and_pay(client, headers, items, method="cash", tab="Kamau", code=None):
    bill = client.post("/api/bills", json={"tab_name": tab}, headers=headers).json()
    bill = client.post(f"/api/bills/{bill['id']}/send", headers=headers,
                       json={"items": [{"sell_option_id": o, "quantity": q} for o, q in items]}).json()
    body = {"method": method, "amount": bill["total"]}
    if code:
        body["mpesa_code"] = code
    r = client.post(f"/api/bills/{bill['id']}/payments", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["bill"]


def today(client, headers):
    return client.get("/api/closing", headers=headers).json()["day"]


def test_real_profit(client, owner, opts):
    tusker = stock_id(client, owner, "Tusker 500ml")
    client.post("/api/stock/deliveries", headers=owner,
                json={"lines": [{"stock_item_id": tusker, "packs": 1, "cost": 5125}]})  # 25 at 205
    sell_and_pay(client, owner, [(opts["Tusker"], 4)])  # 1,200 sales, 820 cost
    client.post("/api/stock/waste", headers=owner, json={"stock_item_id": tusker, "quantity": 1, "reason": "Broken"})
    client.post("/api/stock/takes", headers=owner, json={"counts": [{"stock_item_id": tusker, "full": 19}]})  # 1 missing
    client.post("/api/expenses", headers=owner, json={"category": "rent", "amount": 500})
    client.post("/api/payouts", headers=owner, json={"amount": 100, "reason": "Ice"})

    day = today(client, owner)
    r = client.get(f"/api/reports?start={day}&end={day}", headers=owner).json()
    assert r["profit"] == {
        "sales": 1200, "cost_of_sales": 820, "gross_profit": 380, "waste": 205, "variance": -205,
        "expenses": 600, "expenses_by_category": {"rent": 500, "payouts": 100}, "real_profit": -630,
    }


def test_daily_closing(client, owner, people, opts, db):
    jane, sam = login(client, JANE), login(client, SAM)
    sell_and_pay(client, jane, [(opts["Coke"], 2)])
    sell_and_pay(client, jane, [(opts["Chips"], 1)], method="mpesa", tab="Wanjiru", code="AB12")
    left_open = client.post("/api/bills", json={"tab_name": "Late"}, headers=jane).json()
    bill = client.post(f"/api/bills/{left_open['id']}/send", headers=jane,
                       json={"items": [{"sell_option_id": opts["Tusker"]}]}).json()
    approval = client.post("/api/auth/approvals", headers=jane,
                           json={"action": "void_item", "approver_pin": SAM, "reason": "Not prepared"}).json()["id"]
    client.post(f"/api/bills/{bill['id']}/lines/{bill['lines'][0]['id']}/void", headers=jane,
                json={"reason": "not_prepared", "approval_id": approval})

    day = today(client, sam)
    live = client.get("/api/closing", headers=sam).json()
    report = live["report"]
    assert not live["closed"] and "profit" not in report and report["stock"]["value"] is None
    assert report["sales"] == {"bills": 2, "total": 450, "cash": 200, "mpesa": 250, "card": 0, "credit": 0, "unpaid": 0,
                               "discounts": 0, "tips": 0, "average_bill": 225}
    assert report["voids"] == [{"bill": bill["number"], "item": "Tusker", "price": 300, "reason": "not_prepared",
                                "asked_by": "Jane", "approved_by": "Sam", "at": report["voids"][0]["at"]}]
    assert report["blockers"]["open_shifts"] == ["Jane"]

    r = client.post("/api/closing", json={"day": day}, headers=sam)
    assert r.status_code == 409 and "Jane" in r.json()["detail"]

    client.post(f"/api/bills/{left_open['id']}/close-empty", headers=jane)
    shift = client.get("/api/shifts/me", headers=jane).json()["shift"]["id"]
    client.post(f"/api/shifts/{shift}/close", headers=jane,
                json={"receiver_pin": SAM, "received": 150, "staff_pin": JANE, "agree": True})
    r = client.post("/api/closing", json={"day": day, "cash_box_counted": 150}, headers=sam)
    assert r.status_code == 201, r.text
    closed = r.json()
    assert closed["closed"] and closed["closed_by"] == "Sam" and "profit" not in closed["report"]
    assert closed["report"]["shortages"][0]["difference"] == -50
    assert closed["report"]["cash_box"]["expected_now"] == 150

    # The owner sees the profit in the saved report; nobody can close the day twice.
    mine = client.get(f"/api/closing?day={day}", headers=owner).json()
    assert mine["report"]["profit"]["sales"] == 450
    assert client.post("/api/closing", json={"day": day}, headers=owner).status_code == 409
    assert client.get("/api/closing", headers=jane).status_code == 403


def test_saved_closing_does_not_change(client, owner, people, opts):
    sell_and_pay(client, owner, [(opts["Coke"], 1)])
    day = today(client, owner)
    shift = client.get("/api/shifts/me", headers=owner).json()["shift"]["id"]
    client.post(f"/api/shifts/{shift}/close", headers=owner,
                json={"receiver_pin": "2580", "received": 100, "staff_pin": "2580", "agree": True})
    client.post("/api/closing", json={"day": day}, headers=owner)
    sell_and_pay(client, owner, [(opts["Coke"], 5)])  # same business day, after closing
    assert client.get("/api/closing", headers=owner).json()["report"]["sales"]["total"] == 100


def test_reports_breakdown(client, owner, people, opts):
    jane = login(client, JANE)
    sell_and_pay(client, jane, [(opts["Tusker"], 3), (opts["Chips"], 1)])
    sell_and_pay(client, owner, [(opts["Johnnie Walker Red - Single tot"], 2)], tab="Otieno")
    day = today(client, owner)
    r = client.get(f"/api/reports?start={day}&end={day}", headers=owner).json()
    b = r["breakdown"]
    assert b["best"][0] == {"item": "Tusker", "quantity": 3, "sales": 900}
    assert {c["category"]: c["sales"] for c in b["by_category"]} == {"Beers": 900, "Spirits": 500, "Snacks": 250}
    assert {w["waiter"]: w["sales"] for w in b["by_waiter"]} == {"Jane": 1150, "Njeri": 500}
    assert sum(h["sales"] for h in b["by_hour"]) == 1650
    assert b["worst"][0]["quantity"] == 0  # something on the menu that never sold
    assert client.get(f"/api/reports?start={day}&end={day}", headers=login(client, SAM)).status_code == 403


def test_expenses_are_reversed_not_deleted(client, owner, people):
    e = client.post("/api/expenses", headers=owner,
                    json={"category": "power", "amount": 3000, "note": "KPLC tokens", "from_cash_box": True}).json()
    assert client.get("/api/cashbox", headers=owner).json()["expected"] == -3000
    r = client.post(f"/api/expenses/{e['id']}/reverse", headers=owner)
    assert r.status_code == 201 and r.json()["amount"] == -3000 and r.json()["is_reversal"]
    assert client.post(f"/api/expenses/{e['id']}/reverse", headers=owner).status_code == 409
    assert client.get("/api/cashbox", headers=owner).json()["expected"] == 0
    day = e["business_day"]
    rows = client.get(f"/api/expenses?start={day}&end={day}", headers=owner).json()
    assert len(rows) == 2 and any(row["reversed"] for row in rows)
    assert client.post("/api/expenses", headers=login(client, SAM), json={"category": "rent", "amount": 1}).status_code == 403


def test_dashboard_compares_with_the_same_time_last_week(client, owner, opts, people, db):
    from sqlalchemy import text

    tusker = opts["Tusker"]
    sell_and_pay(client, owner, [(tusker, 2)], tab="A")                       # today
    early = sell_and_pay(client, owner, [(tusker, 1)], tab="B")               # last week, before this time
    late = sell_and_pay(client, owner, [(tusker, 3)], tab="C")                # last week, later in the day
    db.execute(text("UPDATE bills SET business_day = business_day - 7, closed_at = closed_at - interval '7 days' WHERE id = :id"),
               {"id": early["id"]})
    db.execute(text("UPDATE bills SET business_day = business_day - 7, closed_at = closed_at - interval '7 days' + interval '2 hours' "
                    "WHERE id = :id"), {"id": late["id"]})
    db.commit()
    open_bill = client.post("/api/bills", json={"tab_name": "Still drinking"}, headers=owner).json()
    client.post(f"/api/bills/{open_bill['id']}/send", headers=owner, json={"items": [{"sell_option_id": tusker, "quantity": 1}]})

    d = client.get("/api/dashboard", headers=owner).json()
    price = early["total"]
    assert d["today"]["sales"] == 2 * price and d["today"]["bills"] == 1
    assert d["last_week_so_far"]["sales"] == price           # the later bill hadn't happened yet
    assert d["last_week_total"] == 4 * price
    assert sum(d["by_hour"]["today"]) == 2 * price and sum(d["by_hour"]["last_week"]) == 4 * price
    assert d["best"][0]["item"] == "Tusker" and d["best"][0]["quantity"] == 2
    assert d["payments"]["cash"] == 2 * price
    assert d["live"]["open_bills"] == 1 and d["live"]["open_value"] == price
    assert [s["staff"] for s in d["live"]["on_shift"]] == ["Njeri"]
    assert d["recent"][0]["paid_by"] == "cash"
    assert d["gross_profit"] is not None

    sam = login(client, SAM)
    assert client.get("/api/dashboard", headers=sam).json()["gross_profit"] is None  # supervisors: no profit
    assert client.get("/api/dashboard", headers=login(client, JANE)).status_code == 403
