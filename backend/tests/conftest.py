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
CLOUD_DB = os.environ.get(
    "FAIDA_TEST_CLOUD_DATABASE_URL", "postgresql+psycopg://faida@localhost:5544/faida_cloud_test"
)
SECRET = "test-pin-secret"
OWNER_PIN = "2580"


def migrated(url):
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    alembic_cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "migrations"))
    alembic_cfg.attributes["database_url"] = url
    command.upgrade(alembic_cfg, "head")
    return engine


def truncate(engine):
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def engine():
    engine = migrated(TEST_DB)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean(engine):
    yield
    truncate(engine)


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


# The cloud: a second backend in cloud mode, on its own database.


@pytest.fixture(scope="session")
def cloud_engine():
    engine = migrated(CLOUD_DB)
    yield engine
    engine.dispose()


@pytest.fixture
def cloud_db(cloud_engine):
    with Session(cloud_engine, expire_on_commit=False, info={"no_sync_queue": True}) as session:
        yield session
    truncate(cloud_engine)


@pytest.fixture
def cloud(cloud_db):
    app = create_app(Config(mode="cloud", database_url=CLOUD_DB, pin_secret=SECRET, admin_token="admin-token"))
    with TestClient(app) as c:
        yield c


class Link:
    """The counter's internet connection to the test cloud. Set `online` to False to cut it."""

    def __init__(self, cloud_client):
        self.cloud = cloud_client
        self.online = True
        self.calls = 0

    def __call__(self, url, body, token):
        from app.sync.push import SyncError

        self.calls += 1
        if not self.online:
            raise SyncError("Cloud not reachable: no internet")
        r = self.cloud.post("/api/sync/upload", json=body, headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            raise SyncError(f"Cloud refused the upload ({r.status_code}): {r.text}")
        return r.json()


@pytest.fixture
def linked(cloud, cloud_db, business, config, printers):
    """A counter registered with the cloud. Returns (counter client, link, token)."""
    from app.sync.receive import new_device

    _, token = new_device(cloud_db, business.id, "Counter")
    link = Link(cloud)
    counter = create_app(config.model_copy(update={"cloud_url": "http://cloud", "cloud_token": token}),
                         printers=printers, sync_transport=link, start_sync=False)
    with TestClient(counter) as c:
        yield c, link, token
