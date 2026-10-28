"""A counter-only install: the client keeps everything at the bar."""

import json
from datetime import timedelta

import pytest
from conftest import OWNER_PIN, login
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import backup
from app.db import now
from app.main import create_app
from app.sync.models import SyncQueueEntry


@pytest.fixture
def offline(config, printers):
    # A cloud URL left in the settings file by mistake must still send nothing.
    cfg = config.model_copy(update={"offline_only": True, "cloud_url": "http://cloud", "cloud_token": "t"})
    with TestClient(create_app(cfg, printers=printers)) as c:
        yield c


def queued(db):
    return db.scalar(select(func.count()).select_from(SyncQueueEntry))


def test_nothing_is_queued_or_sent(offline, business, db):
    owner = login(offline, OWNER_PIN)
    before = queued(db)
    r = offline.post("/api/tables", json={"name": "T1", "section": "Indoor"}, headers=owner)
    assert r.status_code == 201
    health = offline.get("/api/health").json()
    assert health["cloud"] == "off" and health["waiting_to_sync"] is None
    assert offline.app.state.sync is None
    assert queued(db) == before


def test_a_normal_counter_still_queues(client, business, owner, db):
    before = queued(db)
    client.post("/api/tables", json={"name": "T1", "section": "Indoor"}, headers=owner)
    assert queued(db) > before


@pytest.fixture
def backup_config(config, tmp_path):
    return config.model_copy(update={"backup_passphrase": "phrase", "state_dir": str(tmp_path)})


def write_status(cfg, **fields):
    backup.status_path(cfg).write_text(json.dumps(fields))


def test_backup_problems(config, backup_config):
    at = now()
    assert backup.problem(config.model_copy(update={"backup_passphrase": None}), at) is None  # backups not set up here (development)
    assert "No backup has been made yet" in backup.problem(backup_config, at)
    write_status(backup_config, last_ok_at=(at - timedelta(hours=10)).isoformat(), error=None)
    assert backup.problem(backup_config, at) is None
    write_status(backup_config, last_ok_at=(at - timedelta(hours=40)).isoformat(), error=None)
    assert "No backup since" in backup.problem(backup_config, at)
    write_status(backup_config, last_ok_at=(at - timedelta(hours=30)).isoformat(),
                 error="Backup drive not found", failed_at=at.isoformat())
    assert backup.problem(backup_config, at) == "Last night's backup failed: Backup drive not found"


def test_the_owner_dashboard_warns_about_backups(backup_config, printers, business):
    with TestClient(create_app(backup_config, printers=printers)) as c:
        alerts = c.get("/api/dashboard", headers=login(c, OWNER_PIN)).json()["alerts"]
    assert alerts[0] == {"tone": "bad", "text": "No backup has been made yet. Is the USB drive plugged in?"}
