"""Process configuration, read from environment variables (prefix FAIDA_) or backend/.env.

Business settings that the owner changes (cut-off, auto-lock, tot size...) live in the
database instead; see app/settings/models.py.
"""

import os
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.2.0"


class Config(BaseSettings):
    # An installed counter keeps its settings outside the app folder, so updates and
    # rollbacks never touch them (deploy/ sets FAIDA_ENV_FILE).
    model_config = SettingsConfigDict(env_prefix="FAIDA_", env_file=os.environ.get("FAIDA_ENV_FILE", ".env"), extra="ignore")

    # local = the counter PC (prints, queues sync); cloud = the shared Faida server.
    mode: Literal["local", "cloud"] = "local"
    database_url: str = "postgresql+psycopg://faida@localhost:5544/faida"

    # Secret key used to protect staff PINs. Never stored in the database, so a copied
    # database (e.g. a stolen backup drive) does not reveal anyone's PIN.
    pin_secret: str

    # Business-day and record times are shown in this timezone.
    timezone: str = "Africa/Nairobi"

    # The screen auto-locks after the owner's idle setting (default 30 s). This is the
    # server-side backstop: a session unused for this long is ended regardless.
    session_idle_minutes: int = 10

    # Printers (see app/printing/printers.py for the formats). The counter printer has
    # the cash drawer and prints bar slips, bills and receipts.
    counter_printer: str = "file:prints"
    kitchen_printer: str = "file:prints"

    # Wrong PINs in a row before the keypad pauses, and for how long.
    pin_max_attempts: int = 5
    pin_lockout_seconds: int = 30

    # Counter: where to upload, with the token from `register-device` on the cloud.
    cloud_url: str | None = None
    cloud_token: str | None = None
    sync_interval_seconds: int = 15

    # Backups (python -m app.backup). Always encrypted with this passphrase.
    backup_passphrase: str | None = None
    pg_bin: str | None = None  # PostgreSQL's bin folder, if pg_dump isn't on the PATH
    state_dir: str = "state"  # backup status and other small local files

    # Cloud: Avinaya's admin token for /api/admin/health, and where health alerts go.
    admin_token: str | None = None
    alert_webhook: str | None = None

    # Email for the daily closing report (any SMTP account, e.g. Gmail with an app password).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    # Built frontend to serve (the cloud serves the owner's phone view from here).
    static_dir: str | None = None


@lru_cache
def get_config() -> Config:
    return Config()
