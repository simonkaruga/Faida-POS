from conftest import OWNER_PIN, login
from sqlalchemy import select

from app.audit.models import AuditEntry


def test_health_before_and_after_setup(client, db):
    r = client.get("/api/health").json()
    assert r["set_up"] is False and r["business_name"] is None
    assert client.post("/api/auth/login", json={"pin": OWNER_PIN}).status_code == 503


def test_health_shows_business_name(client, business):
    assert client.get("/api/health").json()["business_name"] == "Test Bar"


def test_owner_logs_in_with_pin_alone(client, business):
    r = client.post("/api/auth/login", json={"pin": OWNER_PIN})
    assert r.status_code == 200
    body = r.json()
    assert body["staff"]["name"] == "Njeri" and body["staff"]["role"] == "owner"
    assert body["permissions"]["manage_business"] == "allow"
    assert body["auto_lock_seconds"] == 30


def test_wrong_pin_then_keypad_pause_then_reset(client, business):
    for _ in range(2):
        assert client.post("/api/auth/login", json={"pin": "9999"}).status_code == 401
    assert client.post("/api/auth/login", json={"pin": "9999"}).status_code == 401
    # Third wrong PIN in a row: keypad pauses, even for the right PIN.
    r = client.post("/api/auth/login", json={"pin": OWNER_PIN})
    assert r.status_code == 429 and "Try again" in r.json()["detail"]


def test_correct_pin_resets_the_wrong_pin_count(client, business):
    for _ in range(2):
        client.post("/api/auth/login", json={"pin": "9999"})
    login(client, OWNER_PIN)
    for _ in range(2):
        assert client.post("/api/auth/login", json={"pin": "9999"}).status_code == 401
    login(client, OWNER_PIN)


def test_lock_ends_the_session(client, owner):
    assert client.get("/api/auth/me", headers=owner).status_code == 200
    assert client.post("/api/auth/lock", headers=owner).status_code == 204
    assert client.get("/api/auth/me", headers=owner).status_code == 401


def test_no_token_or_bad_token(client, business):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_waiter_sees_waiter_permissions(client, waiter):
    perms = client.get("/api/auth/me", headers=waiter).json()["permissions"]
    assert perms["open_bill"] == "own"
    assert perms["void_item"] == "approval"
    assert perms["manage_business"] == "deny"


def test_only_the_owner_manages_staff(client, waiter, supervisor):
    assert client.get("/api/staff", headers=waiter).status_code == 403
    assert client.get("/api/staff", headers=supervisor).status_code == 403
    r = client.post("/api/staff", json={"name": "X", "role": "owner", "pin": "4826"}, headers=supervisor)
    assert r.status_code == 403


def test_pins_must_be_unique_and_strong(client, owner, add_staff):
    add_staff("Jane", "waiter", "1357")
    r = client.post("/api/staff", json={"name": "Ann", "role": "waiter", "pin": "1357"}, headers=owner)
    assert r.status_code == 409
    r = client.post("/api/staff", json={"name": "Ann", "role": "waiter", "pin": "1111"}, headers=owner)
    assert r.status_code == 422


def test_pin_reset(client, owner, add_staff):
    jane = add_staff("Jane", "waiter", "1357")
    r = client.post(f"/api/staff/{jane['id']}/pin", json={"pin": "4826"}, headers=owner)
    assert r.status_code == 204
    assert client.post("/api/auth/login", json={"pin": "1357"}).status_code == 401
    login(client, "4826")


def test_deactivated_staff_are_logged_out_and_kept(client, owner, add_staff):
    jane = add_staff("Jane", "waiter", "1357")
    jane_headers = login(client, "1357")
    r = client.post(f"/api/staff/{jane['id']}/deactivate", headers=owner)
    assert r.json()["active"] is False
    assert client.get("/api/auth/me", headers=jane_headers).status_code == 401
    assert client.post("/api/auth/login", json={"pin": "1357"}).status_code == 401
    names = [s["name"] for s in client.get("/api/staff", headers=owner).json()]
    assert "Jane" in names
    # Their old PIN can now be given to someone new.
    add_staff("Ann", "waiter", "1357")


def test_business_keeps_at_least_one_owner(client, owner, business, db):
    me = client.get("/api/auth/me", headers=owner).json()["staff"]
    assert client.post(f"/api/staff/{me['id']}/deactivate", headers=owner).status_code == 409
    r = client.patch(f"/api/staff/{me['id']}", json={"role": "waiter"}, headers=owner)
    assert r.status_code == 409


def test_staff_changes_are_audited(client, owner, add_staff, db):
    jane = add_staff("Jane", "waiter", "1357")
    client.patch(f"/api/staff/{jane['id']}", json={"role": "supervisor"}, headers=owner)
    client.post(f"/api/staff/{jane['id']}/pin", json={"pin": "4826"}, headers=owner)
    client.post(f"/api/staff/{jane['id']}/deactivate", headers=owner)
    actions = db.scalars(select(AuditEntry.action).order_by(AuditEntry.created_at)).all()
    assert actions == [
        "business.created",
        "staff.login",
        "staff.created",
        "staff.updated",
        "staff.pin_reset",
        "staff.deactivated",
    ]
    updated = db.scalar(select(AuditEntry).where(AuditEntry.action == "staff.updated"))
    assert updated.details == {"role": ["waiter", "supervisor"]}


def test_settings(client, owner, waiter):
    assert client.get("/api/settings", headers=waiter).json()["business_day_cutoff"] == "06:00:00"
    assert client.patch("/api/settings", json={"tot_size_ml": 25}, headers=waiter).status_code == 403
    r = client.patch(
        "/api/settings", json={"tot_size_ml": 25, "mpesa_code_entry": "full"}, headers=owner
    )
    assert r.status_code == 200 and r.json()["tot_size_ml"] == 25
    log = client.get("/api/audit", headers=owner).json()
    assert log[0]["action"] == "settings.updated"
    assert log[0]["details"] == {"tot_size_ml": [None, "25"], "mpesa_code_entry": ["last4", "full"]}
    assert client.get("/api/audit", headers=waiter).status_code == 403


def test_init_business_command(monkeypatch, capsys, config, client):
    import app.cli as cli

    # A refused PIN, then a mismatch, then a good PIN typed twice: it keeps asking.
    pins = iter(["1234", "2580", "2589", "2580", "2580"])
    monkeypatch.setattr(cli, "get_config", lambda: config)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(pins))
    cli.main(["init-business", "--name", "Mama Njeri's", "--owner", "Njeri"])
    err = capsys.readouterr().err
    assert "Nothing shows while you type" in err
    assert "can't be a run of digits like 1234. Try again." in err
    assert "didn't match. Try again." in err
    assert "Set up Mama Njeri's" in err
    assert client.get("/api/health").json()["business_name"] == "Mama Njeri's"
    login(client, "2580")
