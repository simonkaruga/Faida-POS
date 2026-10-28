"""Seeing printouts on screen, and the printer log."""

import pytest
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


def test_58mm_paper_keeps_every_line_on_the_paper(tmp_path):
    from datetime import datetime

    from app.printing import layouts as L
    from app.printing.document import small_width, to_text
    from app.printing.printers import make_printer

    h = L.Header(business="Demo Bar & Restaurant", place="Table 12", waiter="Jane Wanjiru",
                 when=datetime(2026, 10, 19, 21, 5), bill_number=31)
    items = [L.ItemRow(2, "Tusker", None, 600), L.ItemRow(1, "Johnnie Walker Red - Double tot", "no ice", 500, ["+ Coke"])]
    doc = L.receipt(h, 142, items, 1100, 0, [L.PaymentRow("M-Pesa P2QM", 1100)], "Thank you, karibu tena!")
    for row in doc:
        room = small_width(32) if row.get("small") else 32 // row.get("size", 1)
        assert all(len(line) <= room for line in to_text([row], 32).split("\n")), row

    printer = make_printer(f"file:{tmp_path}", "counter", 58)
    printer.print(doc)
    assert "Powered by Faida POS" in next(tmp_path.iterdir()).read_text()
    try:
        make_printer("file:x", "counter", 76)
        raise AssertionError("76 mm accepted")
    except ValueError:
        pass


def test_printer_settings_as_typed_at_install(config, tmp_path):
    """"POS80" typed instead of device:\\\\localhost\\POS80 means that Windows share, and a
    setting Faida can't read never stops the counter from starting."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.printing.printers import DevicePrinter, NoPrinter, make_printer, printer_or_none

    share = make_printer("POS80", "counter", windows=False)
    assert isinstance(share, DevicePrinter) and share.path == r"\\localhost\POS80"
    assert isinstance(printer_or_none("usb???", "counter"), NoPrinter)
    cfg = config.model_copy(update={"counter_printer": "usb???", "kitchen_printer": "usb???"})
    with TestClient(create_app(cfg)) as c:
        assert c.get("/api/health").status_code == 200


@pytest.fixture
def fake_windows(monkeypatch):
    """win32print and pywintypes as on a Windows counter: an Xprinter on USB001 (not
    shared) and Microsoft Print to PDF."""
    import sys
    import types

    jobs, printers = [], [
        {"pPrinterName": "Microsoft Print to PDF", "pShareName": None, "pPortName": "PORTPROMPT:", "Attributes": 0, "Status": 0},
        {"pPrinterName": "XP-80C", "pShareName": None, "pPortName": "USB001", "Attributes": 0, "Status": 0},
    ]
    w = types.SimpleNamespace(
        PRINTER_ENUM_LOCAL=2, PRINTER_ENUM_CONNECTIONS=4,
        EnumPrinters=lambda flags, name, level: printers,
        OpenPrinter=lambda name: {"name": name},
        StartDocPrinter=lambda h, level, info: jobs.append([h["name"], info[2], b""]),
        StartPagePrinter=lambda h: None,
        WritePrinter=lambda h, data: jobs[-1].__setitem__(2, jobs[-1][2] + data),
        EndPagePrinter=lambda h: None, EndDocPrinter=lambda h: None, ClosePrinter=lambda h: None,
    )
    monkeypatch.setitem(sys.modules, "win32print", w)
    monkeypatch.setitem(sys.modules, "pywintypes", types.SimpleNamespace(error=OSError))
    return printers, jobs


def test_windows_prints_through_the_spooler_without_a_share(fake_windows):
    """At Chewaz nothing printed through \\\\localhost\\POS80: the counter runs as SYSTEM,
    and the printer needn't be shared. Old settings and a bare name use the spooler."""
    from app.printing.document import text
    from app.printing.printers import PrinterError, WindowsPrinter, make_printer

    printers, jobs = fake_windows
    for spec in (r"device:\\localhost\POS80", "POS80", "windows:XP-80C"):
        p = make_printer(spec, "counter", windows=True)
        assert isinstance(p, WindowsPrinter)
        p.print([text("Hello")])
    # POS80 isn't a printer's name or share: the only USB printer is used.
    assert [(name, kind) for name, kind, _ in jobs] == [("XP-80C", "RAW")] * 3 and b"Hello" in jobs[0][2]

    printers[1]["Status"] = 0x80
    with pytest.raises(PrinterError, match="offline"):
        make_printer("POS80", "counter", windows=True).print([text("x")])
    printers.append({"pPrinterName": "Other", "pShareName": None, "pPortName": "USB002", "Attributes": 0, "Status": 0})
    with pytest.raises(PrinterError, match="No printer called POS80"):
        make_printer("POS80", "counter", windows=True).print([text("x")])
