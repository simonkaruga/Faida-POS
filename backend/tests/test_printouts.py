"""Seeing printouts on screen, and the printer log."""

from conftest import login


def test_receipt_on_screen_matches_the_printout(client, owner, menu, add_staff):
    add_staff("Jane", "waiter", "1357")
    add_staff("Peter", "waiter", "4826")
    jane = login(client, "1357")
    coke = next(i for c in client.get("/api/menu", headers=jane).json()["categories"] for i in c["items"] if i["name"] == "Coke")
    bill = client.post("/api/bills", json={"tab_name": "Kamau"}, headers=jane).json()
    client.post(f"/api/bills/{bill['id']}/send", headers=jane, json={"items": [{"sell_option_id": coke["options"][0]["id"], "quantity": 2}]})
    paid = client.post(f"/api/bills/{bill['id']}/payments", headers=jane, json={"method": "cash", "amount": 200, "tendered": 500}).json()["bill"]
    receipt = next(t for t in paid["tickets"] if t["kind"] == "receipt")

    doc = client.get(f"/api/tickets/{receipt['id']}", headers=jane).json()
    assert doc["copies"] == [None, "COUNTER COPY"] and doc["title"].startswith("Tab - Kamau")
    texts = [row.get("text") or " ".join(row.get("cols", [])) for row in doc["content"]]
    assert any("2 x Coke" in t for t in texts) and any("Not a KRA tax invoice" in t for t in texts)
    vendor = doc["content"][-1]
    assert vendor["small"] and vendor["text"] == "Powered by Faida POS · Avinaya Solutions Ltd · +254 797 033 513"
    assert "Avinaya" not in " ".join(row.get("text", "") for row in doc["content"] if not row.get("small"))
    assert client.get(f"/api/tickets/{receipt['id']}", headers=login(client, "4826")).status_code == 403

    log = client.get("/api/printouts", headers=owner).json()
    assert [p["kind"] for p in log][:2] == ["receipt", "bar_slip"]
    assert client.get("/api/printouts", headers=jane).status_code == 403
    floor_bill = client.get("/api/floor", headers=owner).json()
    assert floor_bill["bills"] == []


def test_handover_slip_on_screen_and_reprint(client, owner, add_staff, printers):
    add_staff("Sam", "supervisor", "8642")
    sam_id = next(s["id"] for s in client.get("/api/staff", headers=owner).json() if s["name"] == "Sam")
    client.post("/api/shifts/float", headers=owner, json={"staff_id": sam_id, "amount": 100})
    sam = login(client, "8642")
    shift = client.get("/api/shifts/me", headers=sam).json()["shift"]
    client.post(f"/api/shifts/{shift['id']}/close", headers=sam,
                json={"receiver_pin": "2580", "received": 100, "staff_pin": "8642", "agree": True})
    slip = next(p for p in client.get("/api/printouts", headers=owner).json() if p["kind"] == "handover")
    assert slip["title"] == "Hand-over · Sam"
    assert client.get(f"/api/tickets/{slip['id']}", headers=sam).status_code == 200
    r = client.post(f"/api/handover-slips/{slip['id']}/reprint", headers=owner)
    assert r.status_code == 200 and r.json()["reprints"] == 1
    assert "*** REPRINT ***" in printers["counter"].printed[-1]


def test_small_print_fits_the_line_and_uses_the_small_font():
    from app.printing.document import SMALL_WIDTH, to_escpos, to_text
    from app.printing.layouts import VENDOR_LINE, _vendor

    assert len(VENDOR_LINE) <= SMALL_WIDTH
    assert to_text(_vendor()).strip() == VENDOR_LINE
    assert b"\x1bM\x01" in to_escpos(_vendor())  # font B on the printer
