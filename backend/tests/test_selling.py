"""Phase 2: a full round, from order to two receipts, on the counter alone."""

import pytest
from conftest import OWNER_PIN, login
from sqlalchemy import select

from app.audit.models import AuditEntry
from app.printing.models import PrinterName

COUNTER, KITCHEN = PrinterName.counter, PrinterName.kitchen


@pytest.fixture
def opts(client, owner, menu):
    """Sell option ids by display name: "Tusker", "Johnnie Walker Red - Single tot"."""
    out = {}
    for cat in client.get("/api/menu", headers=owner).json()["categories"]:
        for item in cat["items"]:
            for o in item["options"]:
                out[f"{item['name']} - {o['label']}" if o["label"] else item["name"]] = o["id"]
    return out


@pytest.fixture
def tables(client, owner, menu):
    return {t["name"]: t["id"] for t in client.get("/api/floor", headers=owner).json()["tables"]}


def open_table(client, headers, table_id):
    r = client.post("/api/bills", json={"table_id": table_id}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def send(client, headers, bill, *items):
    body = {"items": [{"sell_option_id": o, "quantity": q, "note": n} for o, q, n in items]}
    r = client.post(f"/api/bills/{bill['id']}/send", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def pay(client, headers, bill, **body):
    return client.post(f"/api/bills/{bill['id']}/payments", json=body, headers=headers)


def approve(client, headers, action, pin="8642"):
    r = client.post("/api/auth/approvals", headers=headers,
                    json={"action": action, "approver_pin": pin, "reason": "ok"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def round1(client, waiter, opts, tables):
    """Table T2, Jane: 2 Tusker + 1 Chicken & chips "well done" = 1,250."""
    bill = open_table(client, waiter, tables["T2"])
    return send(client, waiter, bill, (opts["Tusker"], 2, None), (opts["Chicken & chips"], 1, "Well done"))


def test_menu_lists_spirits_with_their_choices(client, waiter, menu):
    cats = {c["name"]: c for c in client.get("/api/menu", headers=waiter).json()["categories"]}
    jw = next(i for i in cats["Spirits"]["items"] if i["name"] == "Johnnie Walker Red")
    assert [o["label"] for o in jw["options"]] == ["Single tot", "Double", "Bottle"]
    tusker = next(i for i in cats["Beers"]["items"] if i["name"] == "Tusker")
    assert tusker["options"] == [{"id": tusker["options"][0]["id"], "label": "", "price": 300}]


def test_send_routes_drinks_to_bar_and_food_to_kitchen(round1, printers):
    assert round1["total"] == 1250 and round1["balance"] == 1250
    assert len(round1["lines"]) == 3
    assert {t["kind"]: t["status"] for t in round1["tickets"]} == {"bar_slip": "printed", "kitchen_ticket": "printed"}
    (slip,) = printers[COUNTER].printed
    (ticket,) = printers[KITCHEN].printed
    assert "2 x Tusker" in slip and "T2" in slip and "Jane" in slip and "Chicken" not in slip
    assert "1 x Chicken & chips" in ticket and "Well done" in ticket and "Tusker" not in ticket


def test_spirit_tots_and_more_rounds_on_the_same_bill(client, waiter, round1, opts):
    bill = send(client, waiter, round1, (opts["Johnnie Walker Red - Single tot"], 2, None))
    assert bill["total"] == 1250 + 500
    assert sum(t["kind"] == "bar_slip" for t in bill["tickets"]) == 2


def test_price_is_fixed_when_ordered(client, owner, waiter, round1, opts):
    r = client.patch(f"/api/menu/options/{opts['Tusker']}", json={"price": 350}, headers=owner)
    assert r.status_code == 204
    assert client.get(f"/api/bills/{round1['id']}", headers=waiter).json()["total"] == 1250
    assert send(client, waiter, round1, (opts["Tusker"], 1, None))["total"] == 1250 + 350
    log = client.get("/api/audit", headers=owner).json()
    assert any(e["action"] == "menu.price_changed" and e["details"]["price"] == ["300", "350"] for e in log)


def test_one_open_bill_per_table_and_named_tabs(client, waiter, owner, tables, round1):
    r = client.post("/api/bills", json={"table_id": tables["T2"]}, headers=owner)
    assert r.status_code == 409 and "Jane" in r.json()["detail"]
    tab = client.post("/api/bills", json={"tab_name": "Kamau"}, headers=waiter).json()
    assert tab["place"] == "Tab - Kamau"
    assert tab["number"] == round1["number"] + 1


def test_waiters_see_only_their_own_bills(client, waiter, owner, add_staff, round1, opts):
    add_staff("Peter", "waiter", "4826")
    peter = login(client, "4826")
    assert client.get(f"/api/bills/{round1['id']}", headers=peter).status_code == 403
    r = client.post(f"/api/bills/{round1['id']}/send", headers=peter,
                    json={"items": [{"sell_option_id": opts["Coke"]}]})
    assert r.status_code == 403 and "Jane" in r.json()["detail"]
    (other,) = client.get("/api/floor", headers=peter).json()["bills"]
    assert other["mine"] is False and other["total"] is None and other["waiter"]["name"] == "Jane"
    (mine,) = client.get("/api/floor", headers=waiter).json()["bills"]
    assert mine["mine"] is True and mine["total"] == 1250
    (seen,) = client.get("/api/floor", headers=owner).json()["bills"]
    assert seen["total"] == 1250
    assert client.get(f"/api/bills/{round1['id']}", headers=owner).status_code == 200


def test_printer_offline_saves_the_order_and_reprints(client, waiter, supervisor, opts, tables, printers):
    printers[KITCHEN].fail = True
    bill = open_table(client, waiter, tables["T6"])
    bill = send(client, waiter, bill, (opts["Chips"], 1, None))
    (ticket,) = bill["tickets"]
    assert ticket["status"] == "not_printed" and bill["total"] == 250
    (row,) = client.get("/api/floor", headers=waiter).json()["bills"]
    assert row["not_printed"] is True

    # Still offline: trying again is free, because it never came out.
    again = client.post(f"/api/tickets/{ticket['id']}/reprint", json={}, headers=waiter).json()
    assert again["tickets"][0]["status"] == "not_printed"

    printers[KITCHEN].fail = False
    fixed = client.post(f"/api/tickets/{ticket['id']}/reprint", json={}, headers=waiter).json()
    assert fixed["tickets"][0]["status"] == "printed"
    assert "REPRINT" not in printers[KITCHEN].printed[0]

    # It came out, so a second copy needs a supervisor.
    r = client.post(f"/api/tickets/{ticket['id']}/reprint", json={}, headers=waiter)
    assert r.status_code == 403
    approval = approve(client, waiter, "reprint_receipt")
    r = client.post(f"/api/tickets/{ticket['id']}/reprint", json={"approval_id": approval}, headers=waiter)
    assert r.status_code == 200
    assert printers[KITCHEN].printed[-1].lstrip().startswith("*** REPRINT ***")


def test_void_needs_approval_and_records_the_reason(client, waiter, supervisor, round1, db):
    line = next(l for l in round1["lines"] if l["item_name"] == "Tusker")
    url = f"/api/bills/{round1['id']}/lines/{line['id']}/void"
    assert client.post(url, json={"reason": "not_prepared"}, headers=waiter).status_code == 403
    approval = approve(client, waiter, "void_item")
    r = client.post(url, json={"reason": "not_prepared", "approval_id": approval}, headers=waiter)
    assert r.status_code == 200
    assert r.json()["total"] == 950
    voided = next(l for l in r.json()["lines"] if l["id"] == line["id"])
    assert voided["voided"] and voided["void_reason"] == "not_prepared"
    entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "bill_line.voided"))
    assert str(entry.approval_id) == approval
    assert client.post(url, json={"reason": "not_prepared"}, headers=supervisor).status_code == 409


def test_cash_payment_shows_change_and_prints_two_receipts(client, waiter, round1, printers):
    r = pay(client, waiter, round1, method="cash", amount=1250, tendered=2000)
    assert r.status_code == 201, r.text
    assert r.json()["change"] == 750
    bill = r.json()["bill"]
    assert bill["status"] == "paid" and bill["balance"] == 0
    receipt = next(t for t in bill["tickets"] if t["kind"] == "receipt")
    assert receipt["status"] == "printed"
    customer, counter = printers[COUNTER].printed[-2:]
    for copy in (customer, counter):
        assert "Not a KRA tax invoice" in copy and "TOTAL" in copy and "2,000 / 750" in copy
    assert "COUNTER COPY" in counter and "COUNTER COPY" not in customer
    client.app.state.printing.flush()
    assert printers[COUNTER].drawer_opened == 1
    assert client.get("/api/floor", headers=waiter).json()["bills"] == []


def test_split_cash_and_mpesa_with_tip(client, waiter, round1, printers):
    first = pay(client, waiter, round1, method="cash", amount=500, tendered=500).json()
    assert first["bill"]["status"] == "open" and first["bill"]["balance"] == 750
    r = pay(client, waiter, round1, method="mpesa", amount=750, tip=200, mpesa_code="p2qm")
    assert r.status_code == 201, r.text
    bill = r.json()["bill"]
    assert bill["status"] == "paid" and bill["paid"] == 1250 and bill["tips"] == 200
    assert bill["payments"][1]["mpesa_ref"] == "P2QM"
    receipt = printers[COUNTER].printed[-1]
    assert "M-Pesa P2QM" in receipt and "Tip (M-Pesa)" in receipt


def test_payment_checks(client, waiter, round1):
    assert pay(client, waiter, round1, method="cash", amount=1300).status_code == 409
    assert pay(client, waiter, round1, method="cash", amount=1250, tendered=1000).status_code == 422
    assert pay(client, waiter, round1, method="cash", amount=1250, tip=50).status_code == 422
    assert pay(client, waiter, round1, method="mpesa", amount=1250, mpesa_code="P2Q").status_code == 422
    assert pay(client, waiter, round1, method="mpesa", amount=1250).status_code == 422


def test_repeated_mpesa_code_needs_approval(client, waiter, owner, supervisor, opts, tables, round1, db):
    assert pay(client, waiter, round1, method="mpesa", amount=1250, mpesa_code="P2QM").status_code == 201
    second = send(client, waiter, open_table(client, waiter, tables["T3"]), (opts["Coke"], 1, None))
    r = pay(client, waiter, second, method="mpesa", amount=100, mpesa_code="P2QM")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "mpesa_duplicate" and detail["bill_number"] == round1["number"]
    assert f"#{round1['number']:04d}" in detail["message"]

    approval = approve(client, waiter, "mpesa_duplicate_override")
    r = pay(client, waiter, second, method="mpesa", amount=100, mpesa_code="P2QM", approval_id=approval)
    assert r.status_code == 201

    third = send(client, owner, open_table(client, owner, tables["T4"]), (opts["Coke"], 1, None))
    assert pay(client, owner, third, method="mpesa", amount=100, mpesa_code="P2QM").status_code == 409
    r = pay(client, owner, third, method="mpesa", amount=100, mpesa_code="P2QM", confirm_duplicate=True)
    assert r.status_code == 201
    accepted = db.scalars(select(AuditEntry).where(AuditEntry.action == "payment.mpesa_duplicate_accepted")).all()
    assert len(accepted) == 2


def test_mpesa_code_entry_setting(client, owner, waiter, round1):
    client.patch("/api/settings", json={"mpesa_code_entry": "full"}, headers=owner)
    assert pay(client, waiter, round1, method="mpesa", amount=100, mpesa_code="P2QM").status_code == 422
    r = pay(client, waiter, round1, method="mpesa", amount=100, mpesa_code="SJK4H7P2QM")
    assert r.json()["bill"]["payments"][0]["mpesa_ref"] == "SJK4H7P2QM"
    client.patch("/api/settings", json={"mpesa_code_entry": "none"}, headers=owner)
    r = pay(client, waiter, round1, method="mpesa", amount=100)
    assert r.status_code == 201 and r.json()["bill"]["payments"][1]["mpesa_ref"] is None


def test_hand_bill_over_with_receivers_pin(client, waiter, add_staff, round1, db):
    add_staff("Peter", "waiter", "4826")
    url = f"/api/bills/{round1['id']}/handover"
    assert client.post(url, json={"to_pin": "9999"}, headers=waiter).status_code == 401
    assert client.post(url, json={"to_pin": "1357"}, headers=waiter).status_code == 409
    r = client.post(url, json={"to_pin": "4826"}, headers=waiter)
    assert r.status_code == 200 and r.json()["waiter"]["name"] == "Peter"
    assert client.get(f"/api/bills/{round1['id']}", headers=waiter).status_code == 403
    peter = login(client, "4826")
    assert pay(client, peter, round1, method="cash", amount=1250).status_code == 201
    assert db.scalar(select(AuditEntry).where(AuditEntry.action == "bill.handed_over"))


def test_move_to_another_table(client, waiter, tables, round1, opts):
    open_table(client, waiter, tables["T3"])
    url = f"/api/bills/{round1['id']}/move"
    assert client.post(url, json={"table_id": tables["T3"]}, headers=waiter).status_code == 409
    r = client.post(url, json={"table_id": tables["T5"]}, headers=waiter)
    assert r.status_code == 200 and r.json()["place"] == "T5"


def test_merge_bills_of_the_same_waiter(client, waiter, owner, tables, opts, round1):
    other = send(client, waiter, open_table(client, waiter, tables["T3"]), (opts["Coke"], 2, None))
    r = client.post(f"/api/bills/{round1['id']}/merge", json={"from_bill_id": other["id"]}, headers=waiter)
    assert r.status_code == 200
    assert r.json()["total"] == 1450 and len(r.json()["lines"]) == 5
    assert client.get(f"/api/bills/{other['id']}", headers=waiter).json()["status"] == "merged"

    owners = open_table(client, owner, tables["T4"])
    r = client.post(f"/api/bills/{round1['id']}/merge", json={"from_bill_id": owners["id"]}, headers=owner)
    assert r.status_code == 409


def test_split_by_items(client, waiter, round1):
    food = [l["id"] for l in round1["lines"] if l["item_name"] == "Chicken & chips"]
    r = client.post(f"/api/bills/{round1['id']}/split", json={"line_ids": food}, headers=waiter)
    assert r.status_code == 201
    new = r.json()
    assert new["total"] == 650 and new["place"] == "T2" and new["number"] == round1["number"] + 1
    assert client.get(f"/api/bills/{round1['id']}", headers=waiter).json()["total"] == 600
    every = [l["id"] for l in client.get(f"/api/bills/{round1['id']}", headers=waiter).json()["lines"]]
    assert client.post(f"/api/bills/{round1['id']}/split", json={"line_ids": every}, headers=waiter).status_code == 409


def test_print_bill_with_till_number(client, owner, waiter, round1, printers):
    client.patch("/api/settings", json={"mpesa_till_number": "5123456"}, headers=owner)
    pay(client, waiter, round1, method="cash", amount=250)
    r = client.post(f"/api/bills/{round1['id']}/print", headers=waiter)
    assert r.status_code == 200
    printed = printers[COUNTER].printed[-1]
    assert "BILL" in printed and "5123456" in printed and "TO PAY" in printed and "1,000" in printed


def test_close_an_empty_bill(client, waiter, tables, round1):
    empty = open_table(client, waiter, tables["T7"])
    assert client.post(f"/api/bills/{empty['id']}/close-empty", headers=waiter).json()["status"] == "cancelled"
    assert client.post(f"/api/bills/{round1['id']}/close-empty", headers=waiter).status_code == 409


def test_bill_numbers_never_repeat(client, waiter, owner, tables):
    numbers = [open_table(client, owner, tables[f"T{i}"])["number"] for i in range(1, 5)]
    assert numbers == sorted(set(numbers)) and len(numbers) == 4
