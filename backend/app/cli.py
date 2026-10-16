"""Install and support commands (masterplan 7.1, 7.2).

On the counter (FAIDA_MODE=local):
    python -m app.cli init-business --name "Mama Njeri's Bar" --owner "Njeri"
    python -m app.cli load-menu ../docs/sample-menu.json
    python -m app.cli load-stock ../docs/sample-menu.json   (stock and recipes only)

On the cloud (FAIDA_MODE=cloud):
    python -m app.cli register-device --business-id <id> --name "Counter"
    python -m app.cli create-owner --business-id <id> --email owner@example.com
    python -m app.cli check-health                       (for cron; exits 1 on problems)

PINs and passwords are asked for at the keyboard so they never appear in shell history.
"""

import argparse
import getpass
import json
import sys
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.auth.pins import WeakPin, check_new_pin, pin_lookup
from app.menu.importer import load_menu, load_stock
from app.settings.config import get_config
from app.settings.models import Business, BusinessSettings
from app.staff.models import Role, Staff
from app.sync import outbox as _sync_queue  # noqa: F401  (registers the listener that queues every change)


def init_business(db: Session, secret: str, name: str, owner_name: str, owner_pin: str) -> Business:
    if db.scalar(select(Business.id)):
        raise SystemExit("This counter already has a business set up.")
    check_new_pin(owner_pin)
    business = Business(name=name)
    db.add(business)
    db.flush()
    db.add(BusinessSettings(business_id=business.id))
    owner = Staff(
        business_id=business.id,
        name=owner_name,
        role=Role.owner,
        pin_lookup=pin_lookup(secret, business.id, owner_pin),
    )
    db.add(owner)
    db.flush()
    audit.record(
        db, business_id=business.id, actor_id=None, action="business.created",
        entity_type="business", entity_id=business.id,
        details={"name": name, "owner": owner_name},
    )
    db.commit()
    return business


def register_device(db: Session, config, args) -> None:
    from app.sync.receive import new_device

    device, token = new_device(db, args.business_id, args.name)
    print(f"Registered {device.name} for business {args.business_id}.", file=sys.stderr)
    print("Put these in the counter's settings file (/etc/faida/counter.env or C:\\Faida\\counter.env;"
          " backend/.env in development). The token is shown only once:", file=sys.stderr)
    print(f"FAIDA_CLOUD_TOKEN={token}")


def create_owner(db: Session, config, args) -> None:
    from app.auth.owner import PASSWORD_MIN, hash_password, new_totp_secret, totp_uri
    from app.sync.models import OwnerAccount

    email = args.email.strip().lower()
    if db.scalar(select(OwnerAccount.id).where(OwnerAccount.email == email)):
        raise SystemExit("That email already has a login.")
    password = getpass.getpass(f"Password for {email} (at least {PASSWORD_MIN} characters): ")
    if len(password) < PASSWORD_MIN:
        raise SystemExit(f"Use at least {PASSWORD_MIN} characters.")
    if getpass.getpass("Type it again: ") != password:
        raise SystemExit("The passwords don't match.")
    secret = new_totp_secret()
    db.add(OwnerAccount(business_id=args.business_id, email=email, password_hash=hash_password(password),
                        totp_secret=secret))
    db.commit()
    print(f"Created the phone login for {email}.", file=sys.stderr)
    print("In the owner's authenticator app (Google Authenticator, Microsoft Authenticator...),", file=sys.stderr)
    print(f"add an account with this key: {secret}", file=sys.stderr)
    print(totp_uri(secret, email))


def check_health(db: Session, config, args) -> None:
    from app.sync.health import all_problems, send_alerts

    problems = all_problems(db)
    for p in problems:
        print(f"{p['business']} ({p['device']}): {p['problem']}")
    if problems and config.alert_webhook:
        send_alerts(config.alert_webhook, problems)
    if problems:
        raise SystemExit(1)
    print("All counters healthy.", file=sys.stderr)


CLOUD_COMMANDS = {"register-device": register_device, "create-owner": create_owner, "check-health": check_health}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-business", help="Set up the business and its owner")
    init.add_argument("--name", required=True, help="Business name, as shown on receipts")
    init.add_argument("--owner", required=True, help="Owner's name")
    menu = commands.add_parser("load-menu", help="Load the menu and tables from a JSON file")
    menu.add_argument("file")
    stock = commands.add_parser("load-stock", help="Add stock items and recipes to the menu already loaded")
    stock.add_argument("file")
    device = commands.add_parser("register-device", help="Cloud: allow a counter to upload for a business")
    device.add_argument("--business-id", required=True, type=uuid.UUID)
    device.add_argument("--name", default="Counter")
    owner = commands.add_parser("create-owner", help="Cloud: create the owner's phone login")
    owner.add_argument("--business-id", required=True, type=uuid.UUID)
    owner.add_argument("--email", required=True)
    commands.add_parser("check-health", help="Cloud: report counters that stopped syncing or backing up")
    args = parser.parse_args(argv)

    config = get_config()
    if args.command in CLOUD_COMMANDS:
        if config.mode != "cloud":
            raise SystemExit("This command runs on the cloud (FAIDA_MODE=cloud).")
        with Session(create_engine(config.database_url), expire_on_commit=False, info={"no_sync_queue": True}) as db:
            CLOUD_COMMANDS[args.command](db, config, args)
        return
    if config.mode != "local":
        raise SystemExit("These commands run on the counter (FAIDA_MODE=local).")
    if args.command in ("load-menu", "load-stock"):
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
        with Session(create_engine(config.database_url), expire_on_commit=False) as db:
            business_id = db.scalar(select(Business.id))
            if business_id is None:
                raise SystemExit("Run init-business first.")
            counts = (load_menu if args.command == "load-menu" else load_stock)(db, business_id, data)
        print("Loaded " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in counts.items()) + ".", file=sys.stderr)
        return
    pin = getpass.getpass("Owner PIN (4-6 digits): ")
    if getpass.getpass("Type it again: ") != pin:
        raise SystemExit("The PINs don't match.")
    try:
        with Session(create_engine(config.database_url), expire_on_commit=False) as db:
            business = init_business(db, config.pin_secret, args.name, args.owner, pin)
    except WeakPin as e:
        raise SystemExit(str(e)) from e
    print(f"Set up {business.name} (business ID {business.id}).", file=sys.stderr)


if __name__ == "__main__":
    main()
