from datetime import timedelta

import pytest
from conftest import login
from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.audit import service as audit
from app.audit.models import AuditEntry
from app.auth.deps import Actor
from app.auth.models import Approval
from app.auth.permissions import Action
from app.auth.service import authorize
from app.db import SyncStatus
from app.staff.models import Staff


def ask(client, headers, approver_pin, action="void_item", decision="approved"):
    return client.post(
        "/api/auth/approvals",
        json={
            "action": action,
            "approver_pin": approver_pin,
            "decision": decision,
            "reason": "Not prepared",
        },
        headers=headers,
    )


def actor_for(db, name):
    return Actor(staff=db.scalar(select(Staff).where(Staff.name == name)), token="t")


def test_supervisor_approves_a_waiter_void(client, waiter, supervisor):
    r = ask(client, waiter, "8642")
    assert r.status_code == 201
    assert r.json()["decision"] == "approved"
    assert r.json()["approved_by"]["name"] == "Sam"


def test_waiter_cannot_approve(client, waiter, add_staff):
    add_staff("Peter", "waiter", "4826")
    assert ask(client, waiter, "4826").status_code == 403


def test_wrong_approver_pin(client, waiter):
    assert ask(client, waiter, "9999").status_code == 401


def test_no_approval_for_actions_the_role_may_do_outright(client, supervisor, owner):
    assert ask(client, supervisor, "2580").status_code == 400


def test_no_approval_for_actions_the_role_may_never_do(client, waiter, owner):
    assert ask(client, waiter, "2580", action="force_close_shift").status_code == 400


def test_approval_is_used_once_for_its_own_action(client, waiter, supervisor, db):
    approval_id = ask(client, waiter, "8642").json()["id"]
    jane = actor_for(db, "Jane")

    with pytest.raises(HTTPException) as e:
        authorize(db, jane, Action.discount, approval_id)
    assert e.value.status_code == 403

    approval = authorize(db, jane, Action.void_item, approval_id)
    audit.record(db, business_id=jane.business_id, actor_id=jane.staff.id,
                 action="bill_line.voided", approval=approval)
    db.commit()

    with pytest.raises(HTTPException) as e:
        authorize(db, jane, Action.void_item, approval_id)
    assert e.value.status_code == 409


def test_database_refuses_a_second_use_of_an_approval(client, waiter, supervisor, db):
    approval = db.get(Approval, ask(client, waiter, "8642").json()["id"])
    for _ in range(2):
        audit.record(db, business_id=approval.business_id, actor_id=None,
                     action="bill_line.voided", approval=approval)
    with pytest.raises(IntegrityError):
        db.commit()


def test_rejected_or_expired_approvals_cannot_be_used(client, waiter, supervisor, db):
    jane = actor_for(db, "Jane")
    rejected = ask(client, waiter, "8642", decision="rejected").json()["id"]
    with pytest.raises(HTTPException, match="rejected"):
        authorize(db, jane, Action.void_item, rejected)

    approved = db.get(Approval, ask(client, waiter, "8642").json()["id"])
    approved.created_at -= timedelta(minutes=3)  # in memory only; the row is permanent
    with pytest.raises(HTTPException, match="expired"):
        authorize(db, jane, Action.void_item, approved.id)


def test_approval_belongs_to_the_waiter_who_asked(client, waiter, supervisor, add_staff, db):
    approval_id = ask(client, waiter, "8642").json()["id"]
    add_staff("Peter", "waiter", "4826")
    with pytest.raises(HTTPException):
        authorize(db, actor_for(db, "Peter"), Action.void_item, approval_id)


def test_waiter_without_approval_and_owner_without_need(client, waiter, owner, db):
    with pytest.raises(HTTPException):
        authorize(db, actor_for(db, "Jane"), Action.void_item)
    assert authorize(db, actor_for(db, "Njeri"), Action.void_item) is None
    with pytest.raises(HTTPException):
        authorize(db, actor_for(db, "Jane"), Action.manage_business)


def test_approvals_are_audited_with_who_asked_and_who_decided(client, waiter, supervisor, db):
    ask(client, waiter, "8642")
    entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "approval.approved"))
    jane, sam = actor_for(db, "Jane"), actor_for(db, "Sam")
    assert entry.created_by == sam.staff.id
    assert entry.details["requested_by"] == str(jane.staff.id)
    assert entry.details["reason"] == "Not prepared"


@pytest.mark.parametrize("table", ["audit_entries", "approvals"])
def test_permanent_rows_cannot_be_edited_or_deleted(client, waiter, supervisor, engine, table):
    ask(client, waiter, "8642")
    column = "action" if table == "audit_entries" else "reason"
    for sql in (f"UPDATE {table} SET {column} = 'changed'", f"DELETE FROM {table}"):
        with engine.connect() as conn, pytest.raises(ProgrammingError, match="permanent"):
            conn.execute(text(sql))


def test_sync_status_can_still_be_marked(client, owner, db):
    db.execute(update(AuditEntry).values(sync_status=SyncStatus.synced))
    db.commit()
    assert set(db.scalars(select(AuditEntry.sync_status))) == {SyncStatus.synced}


def test_login_is_recorded_under_the_person(client, waiter, db):
    jane = actor_for(db, "Jane")
    logins = db.scalars(select(AuditEntry.created_by).where(AuditEntry.action == "staff.login"))
    assert jane.staff.id in set(logins)
    login(client, "1357")
