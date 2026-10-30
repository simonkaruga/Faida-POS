"""Encrypted backup and restore (masterplan 7.1, 10)."""

import os

import pytest
from conftest import TEST_DB
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
