import uuid
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.auth.pins import WeakPin, check_new_pin, pin_lookup
from app.auth.sessions import KeypadGuard, SessionStore
from app.settings.business_day import business_day

NAIROBI = ZoneInfo("Africa/Nairobi")
SIX = time(6, 0)


@pytest.mark.parametrize("pin", ["123", "1234567", "12a4", "0000", "1234", "9876", "456789"])
def test_weak_or_malformed_pins_are_refused(pin):
    with pytest.raises(WeakPin):
        check_new_pin(pin)


@pytest.mark.parametrize("pin", ["1357", "2580", "120934"])
def test_good_pins_are_accepted(pin):
    check_new_pin(pin)


def test_pin_lookup_is_keyed_and_per_business():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert pin_lookup("k", a, "1357") == pin_lookup("k", a, "1357")
    assert pin_lookup("k", a, "1357") != pin_lookup("k", b, "1357")
    assert pin_lookup("k", a, "1357") != pin_lookup("other", a, "1357")
    assert "1357" not in pin_lookup("k", a, "1357")


def nairobi(*args):
    return datetime(*args, tzinfo=NAIROBI)


def test_sale_at_0130_saturday_belongs_to_friday():
    assert business_day(nairobi(2026, 10, 17, 1, 30), SIX, NAIROBI) == date(2026, 10, 16)


def test_cutoff_boundary():
    assert business_day(nairobi(2026, 10, 17, 5, 59), SIX, NAIROBI) == date(2026, 10, 16)
    assert business_day(nairobi(2026, 10, 17, 6, 0), SIX, NAIROBI) == date(2026, 10, 17)


def test_utc_record_times_use_the_local_day():
    # 22:30 UTC on Friday is 01:30 Saturday in Nairobi, which is still Friday's business day.
    assert business_day(datetime(2026, 10, 16, 22, 30, tzinfo=UTC), SIX, NAIROBI) == date(2026, 10, 16)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_session_ends_after_idle_time():
    clock = Clock()
    store = SessionStore(idle_seconds=60, clock=clock)
    token = store.start(uuid.uuid4(), uuid.uuid4())
    clock.t = 59
    assert store.touch(token)
    clock.t = 118  # 59 s after the last use
    assert store.touch(token)
    clock.t = 179
    assert store.touch(token) is None


def test_keypad_pauses_after_repeated_wrong_pins():
    clock = Clock()
    guard = KeypadGuard(max_attempts=3, lockout_seconds=30, clock=clock)
    guard.failed()
    guard.failed()
    assert guard.seconds_locked() == 0
    guard.failed()
    assert guard.seconds_locked() == 30
    clock.t = 29.5
    assert guard.seconds_locked() == 1
    clock.t = 30
    assert guard.seconds_locked() == 0


def test_only_the_owner_closes_the_full_screen(client, owner, waiter, config, tmp_path, monkeypatch):
    monkeypatch.setattr(client.app.state, "config", config.model_copy(update={"state_dir": str(tmp_path)}))
    assert client.post("/api/settings/exit-screen", headers=waiter).status_code == 403
    assert not (tmp_path / "exit-screen.flag").exists()
    assert client.post("/api/settings/exit-screen", headers=owner).status_code == 204
    assert (tmp_path / "exit-screen.flag").exists()  # kiosk.ps1 watches this file
