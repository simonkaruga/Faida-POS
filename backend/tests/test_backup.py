"""Encrypted backup and restore (masterplan 7.1, 10)."""

import os

import pytest
from conftest import OWNER_PIN, TEST_DB
from sqlalchemy import create_engine, text

from app import backup

PG_BIN = os.environ.get("FAIDA_TEST_PG_BIN", "/usr/lib/postgresql/16/bin")
RESTORE_DB = os.environ.get("FAIDA_TEST_RESTORE_DATABASE_URL",
                            "postgresql+psycopg:///faida_restore_test?host=/var/run/postgresql")


@pytest.fixture
def backup_config(config, tmp_path):
    return config.model_copy(update={"backup_passphrase": "correct horse battery staple", "pg_bin": PG_BIN,
                                     "state_dir": str(tmp_path / "state")})


def test_backup_and_restore_round_trip(backup_config, tmp_path, business, menu):
    usb = tmp_path / "usb"
    usb.mkdir()
    path = backup.create(backup_config, str(usb / "faida"))
    assert path.suffix == ".fbk" and path.stat().st_size > 1000
    raw = path.read_bytes()
    assert b"Test Bar" not in raw and b"test-pin-secret" not in raw  # encrypted
    status = backup.read_status(backup_config)
    assert status["last_ok_at"] and status["error"] is None

    result = backup.restore(backup_config, str(path), RESTORE_DB)
    assert result["secrets"].strip() == "FAIDA_PIN_SECRET=test-pin-secret"
    count = "SELECT (SELECT count(*) FROM businesses), (SELECT count(*) FROM sell_options), (SELECT count(*) FROM audit_entries)"
    with create_engine(TEST_DB).connect() as a, create_engine(RESTORE_DB).connect() as b:
        assert a.execute(text(count)).one() == b.execute(text(count)).one()
        # The restored copy keeps its rules: audit entries still can't be changed.
        with pytest.raises(Exception, match="permanent"):
            b.execute(text("DELETE FROM audit_entries"))


def test_restore_replaces_everything_even_newer_tables(backup_config, tmp_path, business):
    """An older backup on a newer counter: tables it doesn't have must go too, or its
    migrations can't create them again (Restore-Backup.bat runs them after)."""
    (tmp_path / "usb").mkdir()
    path = backup.create(backup_config, str(tmp_path / "usb" / "faida"))
    with create_engine(RESTORE_DB).begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS public"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS left_behind (id int)"))
    backup.restore(backup_config, str(path), RESTORE_DB)
    with create_engine(RESTORE_DB).connect() as conn:
        assert conn.execute(text("SELECT to_regclass('public.left_behind')")).scalar() is None
        assert conn.execute(text("SELECT count(*) FROM businesses")).scalar() == 1


def test_wrong_passphrase(backup_config, tmp_path, business):
    (tmp_path / "usb").mkdir()
    path = backup.create(backup_config, str(tmp_path / "usb" / "faida"))
    with pytest.raises(backup.BackupError, match="Wrong passphrase"):
        backup.restore(backup_config.model_copy(update={"backup_passphrase": "guess"}), str(path), RESTORE_DB)


def test_missing_drive_is_recorded_for_the_health_monitor(backup_config, tmp_path):
    with pytest.raises(backup.BackupError, match="USB drive"):
        backup.create(backup_config, str(tmp_path / "not-plugged-in" / "faida"))
    assert "USB drive" in backup.read_status(backup_config)["error"]


def test_only_the_newest_backups_are_kept(backup_config, tmp_path, business, monkeypatch):
    (tmp_path / "usb").mkdir()
    stamps = iter(f"2026101{i}-040000" for i in range(5))

    class Clock:
        @staticmethod
        def now():
            class Stamp:
                def __format__(self, _):
                    return next(stamps)
            return Stamp()

    monkeypatch.setattr(backup, "datetime", Clock)
    for _ in range(5):
        backup.create(backup_config, str(tmp_path / "usb" / "faida"), keep=3)
    names = sorted(p.name for p in (tmp_path / "usb" / "faida").glob("*.fbk"))
    assert names == [f"faida-local-2026101{i}-040000.fbk" for i in (2, 3, 4)]


def test_backups_must_be_encrypted(backup_config, tmp_path):
    (tmp_path / "usb").mkdir()
    with pytest.raises(backup.BackupError, match="PASSPHRASE"):
        backup.create(backup_config.model_copy(update={"backup_passphrase": None}), str(tmp_path / "usb" / "x"))


def test_pg_tools_are_found_on_windows(config, tmp_path, monkeypatch):
    """On Windows the tools are pg_dump.exe: looking for "pg_dump" failed every backup."""
    bin_dir = tmp_path / "PostgreSQL" / "16" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "pg_dump.exe").write_bytes(b"")
    cfg = config.model_copy(update={"pg_bin": str(bin_dir)})
    assert backup._tool(cfg, "pg_dump", windows=True) == str(bin_dir / "pg_dump.exe")
    with pytest.raises(backup.BackupError, match="pg_restore not found in"):
        backup._tool(cfg, "pg_restore", windows=True)
    # No FAIDA_PG_BIN and nothing on the PATH: PostgreSQL's usual folder.
    monkeypatch.setattr(backup.shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert backup._tool(config.model_copy(update={"pg_bin": None}), "pg_dump", windows=True) == str(bin_dir / "pg_dump.exe")


def test_start_afresh_after_trying_faida(client, owner, waiter, menu, backup_config, tmp_path, monkeypatch):
    """Owner only, with their PIN and DELETE typed: every sale, shift, stock movement and
    the log go; the menu, stock items and staff stay. A backup is taken first."""
    monkeypatch.setattr(client.app.state, "config", backup_config)
    cat = client.get("/api/menu", headers=owner).json()["categories"]
    option = next(o["id"] for c in cat for i in c["items"] for o in i["options"] if i["name"] == "Tusker")
    tusker = next(s for s in client.get("/api/stock", headers=owner).json() if s["name"] == "Tusker 500ml")
    client.post("/api/stock/deliveries", headers=owner, json={"lines": [{"stock_item_id": tusker["id"], "units": 10}]})
    bill = client.post("/api/bills", json={"tab_name": "Trial"}, headers=waiter).json()
    client.post(f"/api/bills/{bill['id']}/send", headers=waiter, json={"items": [{"sell_option_id": option}]})
    url, ok = "/api/settings/start-afresh", {"pin": OWNER_PIN, "confirm": "DELETE"}

    assert client.post(url, headers=waiter, json={"pin": "1357", "confirm": "DELETE"}).status_code == 403
    assert client.post(url, headers=owner, json={**ok, "confirm": "delete"}).status_code == 422
    assert client.post(url, headers=owner, json={**ok, "pin": "1357"}).status_code == 403
    r = client.post(url, headers=owner, json=ok)
    assert r.status_code == 200, r.text
    saved = r.json()["backup"]
    assert saved.endswith(".fbk") and os.path.exists(saved) and "update-backups" in saved

    with create_engine(TEST_DB).connect() as conn:
        counts = conn.execute(text("SELECT (SELECT count(*) FROM bills), (SELECT count(*) FROM stock_movements), "
                                   "(SELECT count(*) FROM shifts), (SELECT count(*) FROM sell_options) > 0, "
                                   "(SELECT count(*) FROM staff), (SELECT action FROM audit_entries)")).one()
    assert tuple(counts) == (0, 0, 0, True, 2, "records.started_afresh")
    assert next(s for s in client.get("/api/stock", headers=owner).json() if s["name"] == "Tusker 500ml")["level"] == "0"
    assert client.post("/api/bills", json={"tab_name": "Real"}, headers=waiter).json()["number"] == 1
