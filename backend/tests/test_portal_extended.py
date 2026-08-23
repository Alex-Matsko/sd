"""Расширенный личный кабинет: уведомления, файлы, поиск, отчёт, пароль.

Кабинет умел показывать список и переписку — и всё. Клиент узнавал об ответе,
только если сам открывал заявку; приложить скриншот было нельзя; сплошным
списком за год пользоваться невозможно; пароль навсегда оставался тем, что
продиктовал диспетчер.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response
from sqlalchemy.orm import Session

from app.api.routers.portal import (
    change_my_password,
    get_updates,
    list_my_tickets,
    mark_updates_seen,
)
from app.core.enums import Channel, MessageDirection, Priority, TicketStatus, TicketType
from app.models.contact import Contact, ContactEmail
from app.models.portal_auth import PortalCredential
from app.models.ticket import Ticket
from app.schemas.message import MessageCreate
from app.schemas.portal import PortalPasswordChange
from app.schemas.ticket import TicketCreate
from app.services import messages as messages_service
from app.services import portal
from app.services import tickets as tickets_service


def _ticket(db: Session, contact: Contact, subject: str = "Обращение") -> Ticket:
    return tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.PORTAL, subject=subject,
            manual_priority=Priority.P3, manual_priority_reason="test",
        ),
        actor=None,
    )


def _seen_long_ago(db: Session, contact: Contact) -> None:
    """Ставит отметку «был в кабинете» заведомо в прошлое.

    Через mark_updates_seen тест был бы недостоверен: весь тест идёт в одной
    транзакции, а `now()` в Postgres возвращает время её начала — созданное
    следом сообщение оказалось бы «старше» отметки. В бою каждый запрос это
    своя транзакция, и такого не происходит.
    """
    credential = portal.get_or_create_credential(db, contact)
    credential.last_seen_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.add(credential)
    db.commit()


def _reply(db: Session, ticket: Ticket, body: str, direction=MessageDirection.OUTBOUND):
    return messages_service.add_message(db, ticket, MessageCreate(direction=direction, body=body), author_user=None)


# --- сводка изменений ---------------------------------------------------


def test_support_reply_shows_up_as_new(db: Session, contact: Contact):
    """Клиент узнавал об ответе, только если сам открывал заявку."""
    ticket = _ticket(db, contact, "Не печатает принтер")
    _seen_long_ago(db, contact)
    _reply(db, ticket, "Посмотрели, нужен драйвер")

    updates = get_updates(contact=contact, db=db)

    assert updates.total_new_messages == 1
    assert [u.ticket_id for u in updates.tickets] == [ticket.id]
    assert updates.tickets[0].subject == "Не печатает принтер"


def test_internal_notes_are_not_counted(db: Session, contact: Contact):
    """«Новое сообщение», которого нет на странице, — это ошибка: внутренние
    заметки клиенту не видны."""
    ticket = _ticket(db, contact)
    _seen_long_ago(db, contact)
    _reply(db, ticket, "Похоже на кабель", direction=MessageDirection.INTERNAL_NOTE)

    assert get_updates(contact=contact, db=db).total_new_messages == 0


def test_own_messages_are_not_new(db: Session, contact: Contact):
    ticket = _ticket(db, contact)
    _seen_long_ago(db, contact)
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="Ещё подробность"), author_contact=contact
    )

    assert get_updates(contact=contact, db=db).total_new_messages == 0


def test_status_change_shows_up(db: Session, contact: Contact):
    ticket = _ticket(db, contact)
    _seen_long_ago(db, contact)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)

    updates = get_updates(contact=contact, db=db)
    assert updates.tickets[0].status_changed is True
    assert updates.tickets[0].status == TicketStatus.IN_PROGRESS


def test_marking_seen_clears_the_summary(db: Session, contact: Contact):
    ticket = _ticket(db, contact)
    _seen_long_ago(db, contact)
    _reply(db, ticket, "Ответ")
    assert get_updates(contact=contact, db=db).total_new_messages >= 1

    mark_updates_seen(contact=contact, db=db)
    assert get_updates(contact=contact, db=db).total_new_messages == 0


def test_other_clients_updates_are_invisible(db: Session, contact: Contact, organization):
    """Сводка обязана уважать ту же видимость, что и список заявок."""
    stranger = Contact(organization_id=organization.id, full_name="Чужой контакт")
    db.add(stranger)
    db.commit()

    their_ticket = _ticket(db, stranger, "Чужая заявка")
    _seen_long_ago(db, contact)
    _reply(db, their_ticket, "Ответ чужому")

    assert get_updates(contact=contact, db=db).total_new_messages == 0


# --- поиск и фильтры ----------------------------------------------------


def _list(db, contact, **kwargs):
    return list_my_tickets(response=Response(), contact=contact, db=db, **kwargs)


def test_search_finds_by_subject(db: Session, contact: Contact):
    _ticket(db, contact, "Не печатает принтер")
    _ticket(db, contact, "Не работает почта")

    found = _list(db, contact, q="принтер")
    assert [t.subject for t in found] == ["Не печатает принтер"]


def test_search_finds_by_visible_number(db: Session, contact: Contact):
    """Клиент ищет по номеру, который видит, — OH-1042."""
    ticket = _ticket(db, contact, "Заявка с номером")
    found = _list(db, contact, q=ticket.display_number)
    assert [t.id for t in found] == [ticket.id]


def test_search_does_not_reach_internal_notes(db: Session, contact: Contact):
    """Найти заявку по внутренней заметке значило бы узнать, что она есть."""
    ticket = _ticket(db, contact, "Обычная заявка")
    _reply(db, ticket, "секретное-слово-для-диспетчера", direction=MessageDirection.INTERNAL_NOTE)

    assert _list(db, contact, q="секретное-слово-для-диспетчера") == []


def test_open_only_filter(db: Session, contact: Contact):
    open_ticket = _ticket(db, contact, "Открытая")
    closed = _ticket(db, contact, "Закрытая")
    for step in (TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.CLOSED):
        tickets_service.transition_status(db, closed, step, actor=None)

    ids = {t.id for t in _list(db, contact, open_only=True)}
    assert open_ticket.id in ids and closed.id not in ids


# --- смена пароля -------------------------------------------------------


def test_client_changes_his_own_password(db: Session, contact: Contact):
    """Пароль навсегда оставался тем, что продиктовал диспетчер: он известен
    постороннему человеку и, скорее всего, записан."""
    db.add(ContactEmail(contact_id=contact.id, email="selfservice@romashka.ru", is_primary=True))
    db.commit()
    portal.set_password(db, contact, "vydannyj-parol")

    change_my_password(
        PortalPasswordChange(current_password="vydannyj-parol", new_password="moy-novyj-parol"),
        contact=contact, db=db,
    )

    assert portal.authenticate_with_password(db, "selfservice@romashka.ru", "moy-novyj-parol") is not None
    with pytest.raises(portal.PortalAuthError):
        portal.authenticate_with_password(db, "selfservice@romashka.ru", "vydannyj-parol")


def test_wrong_current_password_is_rejected(db: Session, contact: Contact):
    """Иначе добравшийся до открытой вкладки сменил бы пароль и заперся
    внутри."""
    portal.set_password(db, contact, "vydannyj-parol")

    with pytest.raises(HTTPException) as exc:
        change_my_password(
            PortalPasswordChange(current_password="ne-tot", new_password="moy-novyj-parol"),
            contact=contact, db=db,
        )
    assert exc.value.status_code == 400


# --- отчёт клиенту ------------------------------------------------------


def test_report_requires_the_organization_wide_right(db: Session, contact: Contact):
    """Расход пакета — коммерческая цифра по всей компании, а не
    персональная."""
    from app.api.routers.portal import download_my_report

    contact.can_view_org_tickets = False
    db.add(contact)
    db.commit()

    today = date.today()
    with pytest.raises(HTTPException) as exc:
        download_my_report(year=today.year, month=today.month, contact=contact, db=db)
    assert exc.value.status_code == 403


def test_report_is_generated_for_the_responsible_contact(db: Session, contact: Contact):
    from app.api.routers.portal import download_my_report

    contact.can_view_org_tickets = True
    db.add(contact)
    db.commit()
    _ticket(db, contact, "Заявка для отчёта")

    today = date.today()
    response = download_my_report(year=today.year, month=today.month, contact=contact, db=db)

    assert response.media_type == "application/pdf"
    assert response.body.startswith(b"%PDF")


def test_future_period_is_rejected(db: Session, contact: Contact):
    from app.api.routers.portal import download_my_report

    contact.can_view_org_tickets = True
    db.add(contact)
    db.commit()

    future = date.today() + timedelta(days=400)
    with pytest.raises(HTTPException) as exc:
        download_my_report(year=future.year, month=future.month, contact=contact, db=db)
    assert exc.value.status_code == 400
