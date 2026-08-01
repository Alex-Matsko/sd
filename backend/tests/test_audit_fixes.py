"""Regression tests for defects found in the 2026-08-01 project-wide audit
(docs/decisions.md, "Аудит проекта"). Each test pins one fixed behaviour that
was silently wrong before - grouped here rather than scattered so the audit's
findings stay traceable as a set."""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.routers.users import _guard_admin_scope
from app.core.enums import Channel, Priority, TicketType, UserRole
from app.models.contact import Contact
from app.models.user import User
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services import attachments as attachments_service
from app.services import max_channel, telegram_channel
from app.services import tickets as tickets_service


def _ticket(db: Session, contact: Contact):
    payload = TicketCreate(
        contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.PHONE, subject="Аудит",
        manual_priority=Priority.P3, manual_priority_reason="test",
    )
    return tickets_service.create_ticket(db, payload, actor=None)


# --- clearing assignee/team must actually clear ---------------------------------


def test_assignee_can_be_cleared_by_explicit_null(db: Session, contact: Contact, engineer_user: User):
    """The UI's "Не назначено" option sends assigned_engineer_id: null; the
    old `is not None` check silently dropped it and kept the old assignee."""
    ticket = _ticket(db, contact)
    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=engineer_user.id), actor=None)
    assert ticket.assigned_engineer_id == engineer_user.id

    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=None), actor=None)
    db.refresh(ticket)
    assert ticket.assigned_engineer_id is None


def test_team_can_be_cleared_by_explicit_null(db: Session, contact: Contact):
    from app.models.team import Team

    team = Team(name="Аудит-группа")
    db.add(team)
    db.flush()
    ticket = _ticket(db, contact)
    tickets_service.update_ticket(db, ticket, TicketUpdate(team_id=team.id), actor=None)
    assert ticket.team_id == team.id

    tickets_service.update_ticket(db, ticket, TicketUpdate(team_id=None), actor=None)
    db.refresh(ticket)
    assert ticket.team_id is None


def test_omitted_field_still_leaves_assignee_untouched(db: Session, contact: Contact, engineer_user: User):
    """The flip side: a PATCH that doesn't mention the assignee at all must
    not clear it - which is exactly what `is not None` used to protect."""
    ticket = _ticket(db, contact)
    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=engineer_user.id), actor=None)

    tickets_service.update_ticket(db, ticket, TicketUpdate(category_id=None), actor=None)
    db.refresh(ticket)
    assert ticket.assigned_engineer_id == engineer_user.id


# --- privilege escalation ---------------------------------------------------


def _user(role: UserRole) -> User:
    return User(full_name="X", email="x@example.com", password_hash="x", role=role)


def test_manager_cannot_grant_admin_role():
    with pytest.raises(HTTPException) as exc:
        _guard_admin_scope(_user(UserRole.MANAGER), UserRole.ADMIN)
    assert exc.value.status_code == 403


def test_manager_cannot_modify_an_admin_account():
    with pytest.raises(HTTPException) as exc:
        _guard_admin_scope(_user(UserRole.MANAGER), None, target=_user(UserRole.ADMIN))
    assert exc.value.status_code == 403


def test_manager_may_still_manage_ordinary_staff():
    _guard_admin_scope(_user(UserRole.MANAGER), UserRole.ENGINEER, target=_user(UserRole.DISPATCHER))


def test_admin_may_grant_admin_role():
    _guard_admin_scope(_user(UserRole.ADMIN), UserRole.ADMIN, target=_user(UserRole.ADMIN))


# --- attachment filename sanitizing -----------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\evil.dll", "evil.dll"),
        ("/absolute/path/report.pdf", "report.pdf"),
        ("...hidden", "hidden"),
        ("", "file"),
        ("..", "file"),
        ("normal name.png", "normal name.png"),
    ],
)
def test_safe_filename_reduces_to_one_harmless_component(raw, expected):
    assert attachments_service.safe_filename(raw) == expected


def test_safe_filename_bounds_length_keeping_extension():
    name = attachments_service.safe_filename("a" * 500 + ".pdf")
    assert len(name) <= attachments_service.MAX_STORED_NAME_LENGTH
    assert name.endswith(".pdf")


def test_store_attachment_writes_inside_the_attachments_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "attachments_dir", str(tmp_path))
    attachment = attachments_service.store_attachment(1, "../../escape.txt", b"data", "text/plain")
    assert tmp_path in __import__("pathlib").Path(attachment.stored_path).parents
    assert attachment.filename == "escape.txt"


# --- group chats must not become tickets ------------------------------------


def test_telegram_ignores_group_chat_messages():
    update = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "from": {"id": 5, "first_name": "Кто-то"},
            "chat": {"id": -100500, "type": "group"},
            "text": "болтовня в группе",
        },
    }
    assert telegram_channel._extract_incoming(update) is None


def test_telegram_still_accepts_private_chat():
    update = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "from": {"id": 5, "first_name": "Клиент"},
            "chat": {"id": 5, "type": "private"},
            "text": "не работает почта",
        },
    }
    assert telegram_channel._extract_incoming(update) is not None


def test_max_ignores_non_dialog_chat():
    update = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 7, "name": "Кто-то"},
            "recipient": {"chat_id": 99, "chat_type": "chat"},
            "body": {"text": "болтовня", "mid": "mid.1"},
        },
    }
    assert max_channel._extract_incoming(update) is None


def test_max_still_accepts_dialog():
    update = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 7, "name": "Клиент"},
            "recipient": {"chat_id": 99, "chat_type": "dialog"},
            "body": {"text": "не работает 1С", "mid": "mid.1"},
        },
    }
    assert max_channel._extract_incoming(update) is not None
