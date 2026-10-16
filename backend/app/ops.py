"""Small checks used by the install and update scripts in deploy/ (bash and PowerShell
call these, so the logic lives in one place and is tested).

    python -m app.ops busy              exit 1 if shifts or bills are still open
    python -m app.ops revision          print the database's migration revision
    python -m app.ops set-up            print the business ID; exit 1 if not set up yet
    python -m app.ops wait-healthy --version 0.2.0 [--url ...] [--seconds 90]
"""

import argparse
import json
import sys
import time
import urllib.request

from sqlalchemy import create_engine, text

from app.settings.config import get_config


def busy(database_url: str) -> dict[str, int]:
    """Open shifts and bills. Updates run after closing, never mid-service."""
    with create_engine(database_url).connect() as conn:
        return {
            "open_shifts": conn.scalar(text("SELECT count(*) FROM shifts WHERE status = 'open'")) or 0,
            "open_bills": conn.scalar(text("SELECT count(*) FROM bills WHERE status = 'open'")) or 0,
        }


def revision(database_url: str) -> str:
    with create_engine(database_url).connect() as conn:
        return conn.scalar(text("SELECT version_num FROM alembic_version")) or ""


def healthy(url: str, version: str | None) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            body = json.load(r)
    except (OSError, ValueError) as e:
        return False, f"no answer ({e})"
    if version and body.get("version") != version:
        return False, f"running version {body.get('version')}, expected {version}"
    return True, f"version {body.get('version')}, mode {body.get('mode')}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.ops")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("busy", help="Exit 1 if shifts or bills are still open")
    commands.add_parser("revision", help="Print the database's migration revision")
    commands.add_parser("set-up", help="Print the business ID (to link the cloud); exit 1 if not set up")
    wait = commands.add_parser("wait-healthy", help="Wait until the backend answers with this version")
    wait.add_argument("--url", default="http://127.0.0.1:8000/api/health")
    wait.add_argument("--version")
    wait.add_argument("--seconds", type=int, default=90)
    args = parser.parse_args(argv)

    if args.command == "wait-healthy":
        deadline = time.monotonic() + args.seconds
        while True:
            ok, detail = healthy(args.url, args.version)
            if ok:
                print(f"Healthy: {detail}", file=sys.stderr)
                return
            if time.monotonic() > deadline:
                raise SystemExit(f"Not healthy after {args.seconds} s: {detail}")
            time.sleep(2)

    config = get_config()
    if args.command == "revision":
        print(revision(config.database_url))
        return
    if args.command == "set-up":
        with create_engine(config.database_url).connect() as conn:
            row = conn.execute(text("SELECT id, name FROM businesses")).first()
        if row is None:
            raise SystemExit("Not set up yet.")
        print(f"{row.name}: business ID {row.id}")
        return
    counts = busy(config.database_url)
    if counts["open_shifts"] or counts["open_bills"]:
        raise SystemExit(f"Still in service: {counts['open_shifts']} open shifts, {counts['open_bills']} open bills. "
                         "Update after closing.")
    print("Closed: no open shifts or bills.", file=sys.stderr)


if __name__ == "__main__":
    main()
