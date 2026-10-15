"""Tests run against a real PostgreSQL database (FAIDA_TEST_DATABASE_URL), migrated
with the same migrations the counter and cloud use."""

import json
import os

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.cli import init_business
from app.main import create_app
from app.menu.importer import load_menu
from app.models import Base
from app.printing.document import to_text
from app.printing.models import PrinterName
from app.printing.printers import PrinterError
from app.settings.config import Config

TEST_DB = os.environ.get(
    "FAIDA_TEST_DATABASE_URL", "postgresql+psycopg://faida@localhost:5544/faida_test"
)
SECRET = "test-pin-secret"
OWNER_PIN = "2580"


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DB)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    alembic_cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "migrations"))
    alembic_cfg.attributes["database_url"] = TEST_DB
    command.upgrade(alembic_cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean(engine):
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def db(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def config():
    return Config(
        database_url=TEST_DB, pin_secret=SECRET, pin_max_attempts=3, pin_lockout_seconds=30
    )


class FakePrinter:
    """Records what would have printed, as text. Set `fail` to simulate an offline printer."""

    def __init__(self):
        self.printed: list[str] = []
        self.drawer_opened = 0
        self.fail = False

    def print(self, doc):
        if self.fail:
            raise PrinterError("Printer not reachable")
        self.printed.append(to_text(doc))

    def open_drawer(self):
        self.drawer_opened += 1


@pytest.fixture
def printers():
    return {PrinterName.counter: FakePrinter(), PrinterName.kitchen: FakePrinter()}


@pytest.fixture
def app(config, printers):
    return create_app(config, printers=printers)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def business(db):
    return init_business(db, SECRET, "Test Bar", "Njeri", OWNER_PIN)


SAMPLE_MENU = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "sample-menu.json")


@pytest.fixture
def menu(db, business):
    with open(SAMPLE_MENU, encoding="utf-8") as f:
        load_menu(db, business.id, json.load(f))


def login(client, pin):
    r = client.post("/api/auth/login", json={"pin": pin})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def owner(client, business):
    return login(client, OWNER_PIN)


@pytest.fixture
def add_staff(client, owner):
    def add(name, role, pin):
        r = client.post("/api/staff", json={"name": name, "role": role, "pin": pin}, headers=owner)
        assert r.status_code == 201, r.text
        return r.json()

    return add


@pytest.fixture
def waiter(client, add_staff):
    add_staff("Jane", "waiter", "1357")
    return login(client, "1357")


@pytest.fixture
def supervisor(client, add_staff):
    add_staff("Sam", "supervisor", "8642")
    return login(client, "8642")
