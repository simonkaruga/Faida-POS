"""Phase 3: shifts, credit, cash-up and hand-over. Done when the cash-up maths passes
every test case (masterplan 11)."""

import pytest
from conftest import login
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.audit.models import AuditEntry
from app.printing.models import PrinterName

COUNTER = PrinterName.counter
JANE, PETER, SAM, OWNER = "1357", "4826", "8642", "2580"


@pytest.fixture
def items(client, owner, menu):
    """Items at round prices, so cash-up figures read like the masterplan's."""
    cat = client.get("/api/menu", headers=owner).json()["categories"][0]["id"]
    ids = {}
    for price in (100, 1200, 8100, 9200, 1250, 500, 1000):
        client.post("/api/menu/items", headers=owner, json={
            "category_id": cat, "name": f"Item {price}", "station": "bar", "options": [{"price": price}]})
    for c in client.get("/api/menu", headers=owner).json()["categories"]:
        for i in c["items"]:
            if i["name"].startswith("Item "):
                ids[int(i["name"][5:])] = i["options"][0]["id"]
    return ids


@pytest.fixture
def staff(add_staff):
    add_staff("Jane", "waiter", JANE)
    add_staff("Peter", "waiter", PETER)
    add_staff("Sam", "supervisor", SAM)


@pytest.fixture
def tabs(client):
    counter = iter(range(1, 1000))

    def open_tab(headers, *prices_and_items):
        items, prices = prices_and_items
        bill = client.post("/api/bills", json={"tab_name": f"Tab {next(counter)}"}, headers=headers).json()
        r = client.post(f"/api/bills/{bill['id']}/send", headers=headers,
                        json={"items": [{"sell_option_id": items[p]} for p in prices]})
        assert r.status_code == 200, r.text
        return r.json()

    return open_tab


def pay(client, headers, bill, **body):
    r = client.post(f"/api/bills/{bill['id']}/payments", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["bill"]


def approve(client, headers, action, pin=SAM):
    r = client.post("/api/auth/approvals", headers=headers, json={"action": action, "approver_pin": pin, "reason": "ok"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def customer(client, owner, name="Otieno", limit=2000):
    r = client.post("/api/credit/customers", json={"name": name, "phone": "0712", "credit_limit": limit}, headers=owner)
    assert r.status_code == 201, r.text
    return r.json()


def my_shift(client, headers):
    return client.get("/api/shifts/me", headers=headers).json()


def close(client, headers, shift_id, received=None, notes=None, receiver=OWNER, staff_pin=JANE, agree=True, note=None):
    body = {"receiver_pin": receiver, "staff_pin": staff_pin, "agree": agree, "staff_note": note}
    if notes is not None:
        body["counted_notes"] = notes
    else:
        body["received"] = received
    return client.post(f"/api/shifts/{shift_id}/close", json=body, headers=headers)


def staff_id(client, owner, name):
    return next(s["id"] for s in client.get("/api/staff", headers=owner).json() if s["name"] == name)


def test_masterplan_cash_up_example(client, owner, staff, items, tabs, printers, db):
    """4.6: sales 18,500 - M-Pesa 9,200 - credit 1,200 = 8,100; + float 500 - tip 200 = 8,400."""
    jane = login(client, JANE)
    r = client.post("/api/shifts/float", json={"staff_id": staff_id(client, owner, "Jane"), "amount": 500}, headers=owner)
    assert r.status_code == 200 and r.json()["float_amount"] == 500

    pay(client, jane, tabs(jane, items, [8100]), method="cash", amount=8100, tendered=10000)
    pay(client, jane, tabs(jane, items, [9200]), method="mpesa", amount=9200, tip=200, mpesa_code="P2QM")
    otieno = customer(client, owner)
    bill = tabs(jane, items, [1200])
    r = client.post(f"/api/bills/{bill['id']}/credit", headers=jane,
                    json={"customer_id": otieno["id"], "approval_id": approve(client, jane, "approve_credit")})
    assert r.status_code == 200 and r.json()["status"] == "credit"

    me = my_shift(client, jane)
    assert me["open_bills"] == []
    c = me["cash_up"]
    assert (c["total_sales"], c["mpesa"], c["credit"], c["cash_due_from_sales"]) == (18500, 9200, 1200, 8100)
    assert (c["unpaid_responsible"], c["float_amount"], c["mpesa_tips"], c["cash_to_hand_over"]) == (0, 500, 200, 8400)
    assert [(m["ref"], m["amount"], m["tip"]) for m in c["mpesa_payments"]] == [("P2QM", 9200, 200)]

    # Owner counts by note: 8 x 1000 + 1 x 200 + 1 x 100 + 1 x 50 = 8,350: 50 short.
    r = close(client, jane, me["shift"]["id"], notes={"1000": 8, "200": 1, "100": 1, "50": 1})
    assert r.status_code == 200, r.text
    h = r.json()
    assert (h["expected"], h["received"], h["difference"], h["staff_agrees"]) == (8400, 8350, -50, True)
    assert h["receiver"]["name"] == "Njeri" and h["printed"]
    waiter_copy, owner_copy = printers[COUNTER].printed[-2:]
    assert "WAITER COPY" in waiter_copy and "OWNER COPY" in owner_copy
    assert "SHORT 50" in owner_copy and "8,400" in owner_copy and "AGREES" in owner_copy
    assert my_shift(client, jane)["shift"] is None

    box = client.get("/api/cashbox", headers=owner).json()
    assert box["expected"] == 8350 - 500
    with db.bind.connect() as conn, pytest.raises(ProgrammingError, match="permanent"):
        conn.execute(text("UPDATE handovers SET received = 8400"))


def test_open_bills_block_the_end_of_a_shift(client, owner, staff, items, tabs):
    jane = login(client, JANE)
    bill = tabs(jane, items, [100])
    me = my_shift(client, jane)
    assert [b["number"] for b in me["open_bills"]] == [bill["number"]]
    assert close(client, jane, me["shift"]["id"], received=0).status_code == 409


def test_unpaid_bill_stays_in_cash_due(client, owner, staff, items, tabs):
    jane = login(client, JANE)
    bill = tabs(jane, items, [1250])
    pay(client, jane, bill, method="mpesa", amount=250, mpesa_code="AB12")
    r = client.post(f"/api/bills/{bill['id']}/unpaid", headers=jane)
    assert r.status_code == 200 and r.json()["status"] == "unpaid_responsible"
    c = my_shift(client, jane)["cash_up"]
    assert (c["total_sales"], c["mpesa"], c["cash_due_from_sales"], c["unpaid_responsible"]) == (1250, 250, 1000, 1000)
    assert c["cash_to_hand_over"] == 1000
    # Only the waiter can take this on.
    other = tabs(owner, items, [100])
    assert client.post(f"/api/bills/{other['id']}/unpaid", headers=owner).status_code == 403


def test_cash_taken_before_a_bill_hand_over_stays_with_who_took_it(client, owner, staff, items, tabs):
    jane = login(client, JANE)
    bill = tabs(jane, items, [1250])
    pay(client, jane, bill, method="cash", amount=250)
    client.post(f"/api/bills/{bill['id']}/handover", json={"to_pin": PETER}, headers=jane)
    peter = login(client, PETER)
    pay(client, peter, bill, method="mpesa", amount=1000, mpesa_code="ZZ99")

    j = my_shift(client, jane)["cash_up"]
    assert (j["total_sales"], j["cash_taken_for_others"], j["cash_to_hand_over"]) == (0, 250, 250)
    p = my_shift(client, peter)["cash_up"]
    assert (p["total_sales"], p["mpesa"], p["cash_taken_by_others"], p["cash_to_hand_over"]) == (1250, 1000, 250, 0)


def test_credit_rules(client, owner, staff, items, tabs):
    jane, sam = login(client, JANE), login(client, SAM)
    otieno = customer(client, owner, limit=2000)
    url = lambda b: f"/api/bills/{b['id']}/credit"

    first = tabs(jane, items, [1250])
    assert client.post(url(first), json={"customer_id": otieno["id"]}, headers=jane).status_code == 403
    ok = client.post(url(first), headers=jane, json={"customer_id": otieno["id"], "approval_id": approve(client, jane, "approve_credit")})
    assert ok.status_code == 200

    # 1,250 owed + 1,250 more is over the 2,000 limit: a supervisor can't, the owner can.
    second = tabs(jane, items, [1250])
    r = client.post(url(second), headers=jane, json={"customer_id": otieno["id"], "approval_id": approve(client, jane, "approve_credit")})
    assert r.status_code == 403 and "Only the owner" in r.json()["detail"]
    third = tabs(sam, items, [1250])
    assert client.post(url(third), json={"customer_id": otieno["id"]}, headers=sam).status_code == 403
    r = client.post(url(second), headers=jane,
                    json={"customer_id": otieno["id"], "approval_id": approve(client, jane, "approve_credit", pin=OWNER)})
    assert r.status_code == 200

    (debtor,) = client.get("/api/credit/debtors", headers=sam).json()
    assert (debtor["name"], debtor["owed"], debtor["available"]) == ("Otieno", 2500, 0)
    assert client.get("/api/credit/debtors", headers=jane).status_code == 403

    # Paying it off: cash goes into the counter box, never into Jane's cash-up.
    col = f"/api/credit/customers/{otieno['id']}/collections"
    assert client.post(col, json={"amount": 3000, "method": "cash"}, headers=sam).status_code == 409
    r = client.post(col, json={"amount": 1500, "method": "cash"}, headers=sam)
    assert r.status_code == 201 and r.json()["owed"] == 1000
    assert client.get("/api/cashbox", headers=owner).json()["expected"] == 1500
    assert my_shift(client, jane)["cash_up"]["credit"] == 2500


def test_credit_receipt_names_the_customer(client, owner, staff, items, tabs, printers):
    sam = login(client, SAM)
    otieno = customer(client, owner)
    bill = tabs(sam, items, [1250])
    pay(client, sam, bill, method="cash", amount=250)
    client.post(f"/api/bills/{bill['id']}/credit", json={"customer_id": otieno["id"]}, headers=sam)
    receipt = printers[COUNTER].printed[-1]
    assert "On credit: Otieno" in receipt and "1,000" in receipt


def test_discount_is_net_of_sales(client, owner, staff, items, tabs):
    jane = login(client, JANE)
    bill = tabs(jane, items, [1250])
    url = f"/api/bills/{bill['id']}/discount"
    body = {"kind": "percent", "value": 10, "reason": "Regular"}
    assert client.post(url, json=body, headers=jane).status_code == 403
    r = client.post(url, json={**body, "approval_id": approve(client, jane, "discount")}, headers=jane)
    assert r.status_code == 200
    assert (r.json()["gross"], r.json()["discount"], r.json()["total"]) == (1250, 125, 1125)
    pay(client, jane, bill, method="cash", amount=1125)
    assert my_shift(client, jane)["cash_up"]["total_sales"] == 1125

    other = tabs(owner, items, [1250])
    pay(client, owner, other, method="cash", amount=1000)
    r = client.post(f"/api/bills/{other['id']}/discount", json={"kind": "amount", "value": 500, "reason": "x"}, headers=owner)
    assert r.status_code == 409
    r = client.post(f"/api/bills/{other['id']}/discount", json={"kind": "percent", "value": 150, "reason": "x"}, headers=owner)
    assert r.status_code == 422


def test_cancel_a_paid_bill_reverses_it(client, owner, staff, items, tabs, db):
    jane = login(client, JANE)
    bill = pay(client, jane, tabs(jane, items, [1250]), method="cash", amount=1250)
    url = f"/api/bills/{bill['id']}/cancel"
    assert client.post(url, json={"reason": "already_prepared"}, headers=jane).status_code == 403
    r = client.post(url, json={"reason": "already_prepared", "approval_id": approve(client, jane, "cancel_paid_bill")}, headers=jane)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled" and r.json()["paid"] == 0 and r.json()["payments"][0]["reversed"]
    c = my_shift(client, jane)["cash_up"]
    assert (c["total_sales"], c["cash_to_hand_over"]) == (0, 0)
    entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "bill.cancelled"))
    assert entry.details["refund_cash"] == 1250 and entry.approval_id

    # After the hand-over it's too late: a refund is then a pay-out.
    later = pay(client, jane, tabs(jane, items, [100]), method="cash", amount=100)
    assert close(client, jane, my_shift(client, jane)["shift"]["id"], received=100).status_code == 200
    r = client.post(f"/api/bills/{later['id']}/cancel", json={"reason": "not_prepared"}, headers=owner)
    assert r.status_code == 409 and "pay-out" in r.json()["detail"]


def test_force_close_makes_the_rest_a_shortage(client, owner, staff, items, tabs, db):
    ann = login(client, JANE)
    pay(client, ann, tabs(ann, items, [1000]), method="cash", amount=1000)
    left_open = tabs(ann, items, [500])
    shift_id = my_shift(client, ann)["shift"]["id"]
    sam = login(client, SAM)
    body = {"received": 0, "note": "Left at midnight"}
    assert client.post(f"/api/shifts/{shift_id}/force-close", json=body, headers=sam).status_code == 403
    r = client.post(f"/api/shifts/{shift_id}/force-close", json=body, headers=owner)
    assert r.status_code == 200
    h = r.json()
    assert (h["expected"], h["received"], h["difference"]) == (1500, 0, -1500)
    assert h["forced"] and h["staff_agrees"] is None
    assert client.get(f"/api/bills/{left_open['id']}", headers=owner).json()["status"] == "unpaid_responsible"
    assert db.scalar(select(AuditEntry).where(AuditEntry.action == "shift.force_closed"))


def test_shortage_status_and_pattern_alert(client, owner, staff, items, tabs):
    jane, sam = login(client, JANE), login(client, SAM)
    handovers = []
    for short in (300, 200):
        pay(client, jane, tabs(jane, items, [1000]), method="cash", amount=1000)
        r = close(client, jane, my_shift(client, jane)["shift"]["id"], received=1000 - short, receiver=SAM)
        handovers.append(r.json())
    (alert,) = client.get("/api/shifts/alerts", headers=owner).json()
    assert alert["message"] == "Jane short 2 times this month - KSh 500"
    assert client.get("/api/shifts/alerts", headers=sam).status_code == 403

    url = f"/api/handovers/{handovers[0]['id']}/shortage-status"
    assert client.post(url, json={"outcome": "deducted"}, headers=sam).status_code == 403
    r = client.post(url, json={"outcome": "paid_back", "note": "Paid Friday"}, headers=owner)
    assert r.json()["shortage_status"] == "paid_back"
    rows = client.get("/api/shifts", headers=sam).json()
    assert [row["handover"]["difference"] for row in rows if row["handover"]] == [-300, -200]


def test_overs_are_recorded(client, owner, staff, items, tabs):
    jane = login(client, JANE)
    pay(client, jane, tabs(jane, items, [1000]), method="cash", amount=1000)
    h = close(client, jane, my_shift(client, jane)["shift"]["id"], received=1100).json()
    assert h["difference"] == 100


def test_who_can_receive_and_sign(client, owner, staff, items, tabs):
    jane, sam = login(client, JANE), login(client, SAM)
    pay(client, jane, tabs(jane, items, [100]), method="cash", amount=100)
    shift = my_shift(client, jane)["shift"]["id"]
    assert close(client, jane, shift, received=100, receiver=PETER).status_code == 403
    assert close(client, jane, shift, received=100, staff_pin=PETER).status_code == 403
    assert close(client, jane, shift, received=90, agree=False).status_code == 422
    r = client.post(f"/api/shifts/{shift}/receiver", json={"pin": SAM}, headers=jane)
    assert r.status_code == 200 and r.json()["receiver"]["name"] == "Sam"
    assert close(client, jane, shift, received=90, agree=False, note="I gave 100").status_code == 200

    # A supervisor can't receive their own cash; the owner can.
    pay(client, sam, tabs(sam, items, [100]), method="cash", amount=100)
    sam_shift = my_shift(client, sam)["shift"]["id"]
    assert close(client, sam, sam_shift, received=100, receiver=SAM, staff_pin=SAM).status_code == 403
    assert close(client, sam, sam_shift, received=100, receiver=OWNER, staff_pin=SAM).status_code == 200
    pay(client, owner, tabs(owner, items, [100]), method="cash", amount=100)
    own = my_shift(client, owner)["shift"]["id"]
    assert close(client, owner, own, received=100, receiver=OWNER, staff_pin=OWNER).status_code == 200


def test_payouts_and_the_cash_box(client, owner, staff):
    sam, jane = login(client, SAM), login(client, JANE)
    client.post("/api/cashbox/owner", json={"amount": 2000, "note": "Change for tonight"}, headers=owner)
    r = client.post("/api/payouts", json={"amount": 300, "reason": "Ice"}, headers=sam)
    assert r.status_code == 201 and r.json()["expected"] == 1700
    assert [m["kind"] for m in r.json()["today"]] == ["payout", "owner"]
    assert client.post("/api/payouts", json={"amount": 300, "reason": "Ice"}, headers=jane).status_code == 403
    assert client.post("/api/cashbox/owner", json={"amount": 100, "note": "x"}, headers=sam).status_code == 403


def test_waiters_see_their_finished_bills(client, owner, staff, items, tabs):
    jane = login(client, JANE)
    bill = pay(client, jane, tabs(jane, items, [100]), method="cash", amount=100)
    (row,) = client.get("/api/bills", headers=jane).json()
    assert row["number"] == bill["number"] and row["status"] == "paid"
    assert len(client.get("/api/bills", headers=owner).json()) == 1
