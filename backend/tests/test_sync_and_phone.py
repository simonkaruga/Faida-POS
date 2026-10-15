"""Phase 5: sync and the owner's phone. Done when the phone shows correct numbers after
a 24-hour offline test (masterplan 11)."""

import json
from datetime import timedelta

import pytest
from conftest import OWNER_PIN, SAMPLE_MENU, SECRET
from sqlalchemy import func, select, text

from app.auth.owner import hash_password, new_totp_secret, totp
from app.db import now
from app.floor.models import Bill, BillLine
from app.menu.importer import load_menu
from app.payments.models import Payment
from app.stock.models import RecipeLine
from app.sync.models import Device, OwnerAccount, SyncQueueEntry
from app.sync.push import SyncError

PASSWORD = "a long enough password"


def pin(client, digits):
    r = client.post("/api/auth/login", json={"pin": digits})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def owner_login(cloud_db, business):
    secret = new_totp_secret()
    cloud_db.add(OwnerAccount(business_id=business.id, email="njeri@example.com", password_hash=hash_password(PASSWORD),
                              totp_secret=secret))
    cloud_db.commit()
    return secret


def phone(cloud, secret):
    r = cloud.post("/api/phone/login", json={"email": "njeri@example.com", "password": PASSWORD, "code": totp(secret)})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def options(counter, headers):
    out = {}
    for cat in counter.get("/api/menu", headers=headers).json()["categories"]:
        for item in cat["items"]:
            for o in item["options"]:
                out[f"{item['name']} - {o['label']}" if o["label"] else item["name"]] = o["id"]
    return out


def sale(counter, headers, items, tab, method="cash", code=None):
    bill = counter.post("/api/bills", json={"tab_name": tab}, headers=headers).json()
    bill = counter.post(f"/api/bills/{bill['id']}/send", headers=headers,
                        json={"items": [{"sell_option_id": o, "quantity": q} for o, q in items]}).json()
    body = {"method": method, "amount": bill["total"], **({"mpesa_code": code} if code else {})}
    assert counter.post(f"/api/bills/{bill['id']}/payments", json=body, headers=headers).status_code == 201
    return bill


def count(engine_or_db, model):
    return engine_or_db.scalar(select(func.count()).select_from(model))


def test_a_day_offline_then_the_phone_matches_the_counter(linked, cloud, cloud_db, db, business, owner_login):
    counter, link, _ = linked
    with open(SAMPLE_MENU, encoding="utf-8") as f:
        load_menu(db, business.id, json.load(f))
    owner = pin(counter, OWNER_PIN)
    counter.app.state.sync.push_all()  # online at opening

    link.online = False  # the internet drops for the whole night
    opts = options(counter, owner)
    sale(counter, owner, [(opts["Tusker"], 2), (opts["Chicken & chips"], 1)], "Table 2")
    sale(counter, owner, [(opts["Johnnie Walker Red - Single tot"], 2)], "Kamau", method="mpesa", code="P2QM")
    sale(counter, owner, [(opts["Coke"], 3)], "Otieno")
    counter.post("/api/payouts", headers=owner, json={"amount": 300, "reason": "Ice"})
    with pytest.raises(SyncError):
        counter.app.state.sync.push_all()
    health = counter.get("/api/health").json()
    assert health["cloud"] == "offline" and health["waiting_to_sync"] > 0

    link.online = True  # back the next morning
    assert counter.app.state.sync.push_all() > 0
    assert counter.get("/api/health").json()["waiting_to_sync"] == 0
    assert counter.get("/api/health").json()["cloud"] == "online"

    for model in (Bill, BillLine, Payment):
        assert count(cloud_db, model) == count(db, model)
    local = counter.get("/api/closing", headers=owner).json()["report"]
    on_phone = cloud.get("/api/phone/closing", headers=phone(cloud, owner_login)).json()
    assert on_phone["report"]["sales"] == local["sales"]
    assert on_phone["report"]["profit"] == local["profit"]
    assert on_phone["report"]["cash_box"] == local["cash_box"]
    assert on_phone["last_updated"] is not None

    today = cloud.get("/api/phone/today", headers=phone(cloud, owner_login)).json()
    assert today["business_name"] == "Test Bar"
    assert today["sales"]["total"] == 600 + 650 + 500 + 300
    assert (today["sales"]["cash"], today["sales"]["mpesa"]) == (1550, 500)


def test_uploads_are_safe_to_repeat(linked, cloud_db, db):
    counter, link, token = linked
    owner = pin(counter, OWNER_PIN)
    counter.post("/api/payouts", headers=owner, json={"amount": 300, "reason": "Ice"})
    entries = db.scalars(select(SyncQueueEntry).order_by(SyncQueueEntry.seq)).all()
    body = {"software_version": "0.1.0", "counter_time": now().isoformat(),
            "entries": [dict(seq=e.seq, table=e.table_name, op=e.op, id=str(e.row_id), data=e.payload) for e in entries]}
    for _ in range(2):  # the answer to the first upload was lost; the counter sends it again
        r = link.cloud.post("/api/sync/upload", json=body, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
    counter.app.state.sync.push_all()
    with cloud_db.bind.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM cash_movements")) == 1
        assert conn.scalar(text("SELECT count(*) FROM audit_entries WHERE action = 'cash.payout'")) == 1
        assert conn.scalar(text("SELECT count(*) FROM cash_movements WHERE sync_status = 'synced'")) == 1
    # Back at the counter, uploaded rows are marked synced.
    with db.bind.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM cash_movements WHERE sync_status = 'pending'")) == 0


def test_a_counter_can_only_upload_its_own_business(linked, cloud, cloud_db, db):
    import uuid

    from app.sync.receive import new_device

    counter, _, _ = linked
    counter.app.state.sync.push_all()
    _, other_token = new_device(cloud_db, uuid.uuid4(), "Someone else's counter")
    staff_row = db.execute(text("SELECT to_jsonb(s) FROM staff s LIMIT 1")).scalar()
    body = {"software_version": "0.1.0", "counter_time": now().isoformat(),
            "entries": [dict(seq=1, table="staff", op="upsert", id=staff_row["id"], data={**staff_row, "name": "Hacked"})]}
    r = cloud.post("/api/sync/upload", json=body, headers={"Authorization": f"Bearer {other_token}"})
    assert r.status_code == 403
    assert cloud.post("/api/sync/upload", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_old_counters_keep_syncing_but_too_old_ones_are_refused(linked, cloud, cloud_db):
    _, _, token = linked
    upload = lambda version, at=None: cloud.post(  # noqa: E731
        "/api/sync/upload", headers={"Authorization": f"Bearer {token}"},
        json={"software_version": version, "counter_time": (at or now()).isoformat(), "entries": []})
    assert upload("0.1.0").status_code == 200
    assert upload("0.0.9").status_code == 200  # the previous minor version
    assert upload("1.0.0").status_code == 426
    r = upload("0.1.0", now() + timedelta(minutes=12))
    assert r.json()["clock_warning"] is True
    device = cloud_db.scalar(select(Device))
    cloud_db.refresh(device)
    assert device.clock_offset_seconds >= 700


def test_deleted_rows_are_deleted_in_the_cloud(linked, cloud_db, db, business):
    counter, _, _ = linked
    with open(SAMPLE_MENU, encoding="utf-8") as f:
        load_menu(db, business.id, json.load(f))
    owner = pin(counter, OWNER_PIN)
    counter.app.state.sync.push_all()
    smokie = next(r for r in counter.get("/api/stock/recipes", headers=owner).json() if r["item_name"] == "Smokie")
    counter.put(f"/api/stock/recipes/{smokie['sell_option_id']}", headers=owner, json={"lines": []})
    counter.app.state.sync.push_all()
    assert count(cloud_db, RecipeLine) == count(db, RecipeLine) == 32 - 1  # Smokie had one line


def test_phone_login_needs_password_and_code(cloud, owner_login, linked):
    linked[0].app.state.sync.push_all()
    bad = [{"password": "wrong password", "code": totp(owner_login)}, {"password": PASSWORD, "code": "000000"}]
    for body in bad:
        r = cloud.post("/api/phone/login", json={"email": "njeri@example.com", **body})
        assert r.status_code == 401
    assert cloud.get("/api/phone/today").status_code == 401
    assert cloud.get("/api/phone/today", headers=phone(cloud, owner_login)).status_code == 200
    for _ in range(5):
        cloud.post("/api/phone/login", json={"email": "njeri@example.com", "password": "x", "code": "000000"})
    r = cloud.post("/api/phone/login", json={"email": "njeri@example.com", "password": PASSWORD, "code": totp(owner_login)})
    assert r.status_code == 429


def test_phone_is_read_only_and_counter_endpoints_are_not_in_the_cloud(cloud, owner_login, linked):
    linked[0].app.state.sync.push_all()
    headers = phone(cloud, owner_login)
    for path in ("/api/phone/today", "/api/phone/closing", "/api/phone/stock", "/api/phone/profit", "/api/phone/debtors"):
        assert cloud.get(path, headers=headers).status_code == 200, path
    assert cloud.post("/api/auth/login", json={"pin": OWNER_PIN}).status_code == 404
    assert cloud.post("/api/bills", json={"tab_name": "x"}, headers=headers).status_code == 404


def test_health_monitor_flags_a_silent_counter(cloud, cloud_db, linked, owner_login):
    counter, link, _ = linked
    counter.app.state.sync.push_all()
    assert cloud.get("/api/admin/health").status_code == 401
    problems = cloud.get("/api/admin/health", headers={"X-Admin-Token": "admin-token"}).json()["problems"]
    assert [p["problem"] for p in problems] == ["No backup to USB in the last 36 hours"]

    device = cloud_db.scalar(select(Device))
    cloud_db.execute(text("UPDATE devices SET last_sync_at = now() - interval '25 hours', last_backup_at = now()"))
    cloud_db.commit()
    problems = cloud.get("/api/admin/health", headers={"X-Admin-Token": "admin-token"}).json()["problems"]
    assert len(problems) == 1 and problems[0]["problem"].startswith("The counter hasn't synced since")
    assert problems[0]["business"] == "Test Bar" and problems[0]["device"] == device.name
    alerts = cloud.get("/api/phone/today", headers=phone(cloud, owner_login)).json()["alerts"]
    assert any("hasn't synced" in a for a in alerts)


def test_backup_status_travels_with_the_upload(linked, cloud_db, config):
    counter, link, _ = linked
    counter.app.state.sync._backup_status = lambda: {"last_ok_at": now().isoformat(), "error": None}
    counter.app.state.sync.push_all()
    device = cloud_db.scalar(select(Device))
    cloud_db.refresh(device)
    assert device.last_backup_at is not None and device.backup_error is None
    assert SECRET  # the test cloud signs phone tokens with the same secret setting
