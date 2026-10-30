"""Encrypted backups (masterplan 7.1, 7.2, 10).

    python -m app.backup create --to /media/usb/faida     nightly, at the counter
    python -m app.backup restore --file faida-local-20261016-0400.fbk

A backup holds the database and the PIN secret (without it staff PINs stop working
after a restore), so it is always encrypted with FAIDA_BACKUP_PASSPHRASE. Keep that
passphrase somewhere safe away from the counter: without it a backup can't be opened.
The result is written to a status file. The owner's dashboard warns when backups fail
or stop, and a linked counter also sends it to the cloud so Avinaya is alerted.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import psycopg
from cryptography.fernet import Fernet, InvalidToken

from app.db import now
from app.settings.config import VERSION, Config, get_config

MAGIC = b"FAIDA-BACKUP-1\n"
KEEP = 14
LATE = timedelta(hours=36)  # nightly, with room for a PC that was off for a night


class BackupError(Exception):
    pass


def _key(passphrase: str, salt: bytes) -> bytes:
    return base64.urlsafe_b64encode(hashlib.scrypt(passphrase.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32))


def _tool(config: Config, name: str, windows: bool = os.name == "nt") -> str:
    """pg_dump or pg_restore: in FAIDA_PG_BIN if set, else on the PATH, else (Windows) in
    PostgreSQL's usual folder. On Windows the file is name.exe."""
    files = [f"{name}.exe", name] if windows else [name]
    folders = [Path(config.pg_bin)] if config.pg_bin else []
    if not folders:
        if found := shutil.which(name):
            return found
        if windows:
            folders = sorted(Path(os.environ.get("ProgramFiles", r"C:\Program Files")).glob("PostgreSQL/*/bin"), reverse=True)
    for folder in folders:
        for file in files:
            if (folder / file).is_file():
                return str(folder / file)
    where = f" in {config.pg_bin}" if config.pg_bin else ""
    raise BackupError(f"{name} not found{where}. Set FAIDA_PG_BIN to PostgreSQL's bin folder.")


def _libpq(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def status_path(config: Config) -> Path:
    return Path(config.state_dir) / "backup-status.json"


def read_status(config: Config) -> dict:
    try:
        return json.loads(status_path(config).read_text())
    except (OSError, ValueError):
        return {}


def problem(config: Config, at: datetime) -> str | None:
    """What the owner should know about backups, or None. Silent where backups aren't set
    up (no passphrase), e.g. on a development machine."""
    if not config.backup_passphrase:
        return None
    status = read_status(config)
    last = datetime.fromisoformat(status["last_ok_at"]) if status.get("last_ok_at") else None
    if status.get("error"):  # a good backup clears it
        return f"Last night's backup failed: {status['error']}"
    if last is None:
        return "No backup has been made yet. Is the USB drive plugged in?"
    if at - last > LATE:
        return f"No backup since {last.astimezone(at.tzinfo):%d %b}. Is the USB drive plugged in?"
    return None


def _write_status(config: Config, **fields) -> None:
    path = status_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    status = {**read_status(config), **fields}
    path.write_text(json.dumps(status, indent=2))


def create(config: Config, to_dir: str, keep: int = KEEP) -> Path:
    """Dump, bundle with the secrets, encrypt, write, and keep only the newest `keep`."""
    try:
        if not config.backup_passphrase:
            raise BackupError("FAIDA_BACKUP_PASSPHRASE is not set; backups are always encrypted.")
        target = Path(to_dir)
        if not target.parent.exists():
            raise BackupError(f"Backup drive not found at {target.parent}. Is the USB drive plugged in?")
        target.mkdir(parents=True, exist_ok=True)
        dump = subprocess.run([_tool(config, "pg_dump"), "--format=custom", "--no-owner", "--dbname",
                               _libpq(config.database_url)], capture_output=True, check=False)
        if dump.returncode:
            raise BackupError(f"pg_dump failed: {dump.stderr.decode(errors='replace')[:200]}")
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("database.dump", dump.stdout)
            z.writestr("secrets.env", f"FAIDA_PIN_SECRET={config.pin_secret}\n")
            z.writestr("info.json", json.dumps({"version": VERSION, "mode": config.mode, "created_at": now().isoformat()}))
        salt = secrets.token_bytes(16)
        sealed = MAGIC + salt + Fernet(_key(config.backup_passphrase, salt)).encrypt(bundle.getvalue())
        path = target / f"faida-{config.mode}-{datetime.now():%Y%m%d-%H%M%S}.fbk"
        partial = path.with_suffix(".partial")
        partial.write_bytes(sealed)
        os.replace(partial, path)  # a half-written file never looks like a backup
        for old in sorted(target.glob(f"faida-{config.mode}-*.fbk"))[:-keep]:
            old.unlink()
    except (BackupError, OSError) as e:
        _write_status(config, error=str(e), failed_at=now().isoformat())
        raise BackupError(str(e)) from e
    _write_status(config, last_ok_at=now().isoformat(), file=str(path), error=None)
    return path


def open_backup(passphrase: str, file: str) -> dict[str, bytes]:
    data = Path(file).read_bytes()
    if not data.startswith(MAGIC):
        raise BackupError("This is not a Faida backup file.")
    salt, token = data[len(MAGIC):len(MAGIC) + 16], data[len(MAGIC) + 16:]
    try:
        plain = Fernet(_key(passphrase, salt)).decrypt(token)
    except InvalidToken as e:
        raise BackupError("Wrong passphrase, or the file is damaged.") from e
    with zipfile.ZipFile(io.BytesIO(plain)) as z:
        return {name: z.read(name) for name in z.namelist()}


def restore(config: Config, file: str, database_url: str) -> dict:
    """Restore into `database_url`, replacing everything there. Returns the backup's info
    and the secrets line to put in the restored counter's .env. The database is emptied
    first: a backup from an older version has fewer tables, and newer ones left behind
    would stop its migrations running again."""
    parts = open_backup(config.backup_passphrase or "", file)
    tool = _tool(config, "pg_restore")
    with psycopg.connect(_libpq(database_url), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp) / "database.dump"
        dump.write_bytes(parts["database.dump"])
        result = subprocess.run([tool, "--no-owner", "--dbname", _libpq(database_url), str(dump)],
                                capture_output=True, check=False)
    if result.returncode:
        raise BackupError(f"pg_restore failed: {result.stderr.decode(errors='replace')[:300]}")
    return {"info": json.loads(parts["info.json"]), "secrets": parts["secrets.env"].decode()}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.backup")
    commands = parser.add_subparsers(dest="command", required=True)
    c = commands.add_parser("create", help="Write an encrypted backup")
    c.add_argument("--to", required=True, help="Folder, e.g. on the USB drive")
    c.add_argument("--keep", type=int, default=KEEP)
    r = commands.add_parser("restore", help="Restore a backup into a database")
    r.add_argument("--file", required=True)
    r.add_argument("--database", help="Defaults to FAIDA_DATABASE_URL")
    args = parser.parse_args(argv)
    config = get_config()
    try:
        if args.command == "create":
            print(f"Backup written: {create(config, args.to, args.keep)}", file=sys.stderr)
        else:
            result = restore(config, args.file, args.database or config.database_url)
            print(f"Restored backup from {result['info']['created_at']} (version {result['info']['version']}).",
                  file=sys.stderr)
            print("Put this line in backend/.env, or staff PINs won't work:", file=sys.stderr)
            print(result["secrets"].strip())
    except BackupError as e:
        raise SystemExit(f"Backup failed: {e}") from e


if __name__ == "__main__":
    main()
