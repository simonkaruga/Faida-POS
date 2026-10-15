"""Process configuration, read from environment variables (prefix FAIDA_) or backend/.env.

Business settings that the owner changes (cut-off, auto-lock, tot size...) live in the
database instead; see app/settings/models.py.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.1.0"


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FAIDA_", env_file=".env", extra="ignore")

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

    # Wrong PINs in a row before the keypad pauses, and for how long.
    pin_max_attempts: int = 5
    pin_lockout_seconds: int = 30


@lru_cache
def get_config() -> Config:
    return Config()
