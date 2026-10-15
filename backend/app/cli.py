"""Install-time commands, run on the counter (masterplan 7.1 step 5).

    python -m app.cli init-business --name "Mama Njeri's Bar" --owner "Njeri"

The owner's PIN is asked for at the keyboard so it never appears in shell history.
"""

import argparse
import getpass
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.auth.pins import WeakPin, check_new_pin, pin_lookup
from app.settings.config import get_config
from app.settings.models import Business, BusinessSettings
from app.staff.models import Role, Staff


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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-business", help="Set up the business and its owner")
    init.add_argument("--name", required=True, help="Business name, as shown on receipts")
    init.add_argument("--owner", required=True, help="Owner's name")
    args = parser.parse_args(argv)

    config = get_config()
    if config.mode != "local":
        raise SystemExit("init-business runs on the counter (FAIDA_MODE=local).")
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
