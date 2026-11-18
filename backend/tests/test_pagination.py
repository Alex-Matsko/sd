"""Pagination across the ticket queue (SD interface) and the bots' "Мои
заявки" list. Both were previously unbounded - the queue returned every
ticket, the bots took a fixed newest-10 window."""
from tests.ticket_fixtures import accepted_result

from sqlalchemy.orm import Session

from app.api.routers.tickets import _search_filter
from app.core.enums import Channel, Priority, TicketStatus, TicketType
from app.models.contact import Contact
from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate
from app.services import messenger_common
from app.services import tickets as tickets_service


def _make(db: Session, contact: Contact, subject: str) -> Ticket:
    return tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.PHONE, subject=subject,
            manual_priority=Priority.P3, manual_priority_reason="test",
        ),
        actor=None,
    )


def _close(db: Session, ticket: Ticket) -> None:
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    accepted_result(db, ticket)
    tickets_service.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)


# --- server-side search -------------------------------------------------


def test_search_matches_subject(db: Session, contact: Contact):
    ticket = _make(db, contact, "Не печатает принтер в бухгалтерии")
    found = _search_filter(db.query(Ticket).filter(Ticket.contact_id == contact.id), "принтер").all()
    assert ticket.id in [t.id for t in found]


def test_search_by_display_number(db: Session, contact: Contact):
    """People search by the OH-N they see, but display_number is a Python
    property - the query has to be translated back to the numeric column."""
    ticket = _make(db, contact, "Тема без совпадения")
    for query in (ticket.display_number, ticket.display_number.lower(), str(ticket.number)):
        found = _search_filter(db.query(Ticket), query).all()
        assert [t.id for t in found] == [ticket.id], query


def test_search_ignores_unrelated_tickets(db: Session, contact: Contact):
    _make(db, contact, "Совсем другая тема")
    found = _search_filter(db.query(Ticket).filter(Ticket.contact_id == contact.id), "принтер-которого-нет").all()
    assert found == []


# --- bot "Мои заявки" paging -------------------------------------------


def test_my_tickets_page_returns_page_and_total(db: Session, contact: Contact):
    created = [_make(db, contact, f"Заявка {i}") for i in range(7)]
    items, total = messenger_common.my_tickets_page(db, contact, offset=0)
    assert total == len(created)
    assert len(items) == messenger_common.MY_TICKETS_PAGE_SIZE

    second, _ = messenger_common.my_tickets_page(db, contact, offset=messenger_common.MY_TICKETS_PAGE_SIZE)
    assert len(second) == min(messenger_common.MY_TICKETS_PAGE_SIZE, len(created) - messenger_common.MY_TICKETS_PAGE_SIZE)
    assert {t.id for t in items}.isdisjoint({t.id for t in second})


def test_open_tickets_come_first_even_when_older_than_closed_ones(db: Session, contact: Contact):
    """The old implementation took the newest N and only then floated open
    tickets up, so an open ticket older than N closed ones vanished from the
    list entirely - the one the client most likely wanted."""
    old_open = _make(db, contact, "Старая открытая")
    for i in range(6):
        _close(db, _make(db, contact, f"Свежая закрытая {i}"))

    items, total = messenger_common.my_tickets_page(db, contact, offset=0)
    assert total == 1
    assert items[0].id == old_open.id


def test_buttons_offer_next_page_only_when_more_remain(db: Session, contact: Contact):
    for i in range(7):
        _make(db, contact, f"Заявка {i}")

    items, total = messenger_common.my_tickets_page(db, contact, offset=0)
    payloads = [row[0]["payload"] for row in messenger_common.my_tickets_buttons(items, 0, total)]
    assert f"mytickets:active:{messenger_common.MY_TICKETS_PAGE_SIZE}" in payloads
    assert not any(button["text"] == "← Назад" for row in messenger_common.my_tickets_buttons(items, 0, total) for button in row)

    tail_offset = 2 * messenger_common.MY_TICKETS_PAGE_SIZE
    tail, _ = messenger_common.my_tickets_page(db, contact, offset=tail_offset)
    tail_payloads = [button['payload'] for row in messenger_common.my_tickets_buttons(tail, tail_offset, total) for button in row]
    assert f"mytickets:active:{tail_offset - messenger_common.MY_TICKETS_PAGE_SIZE}" in tail_payloads
    assert not any(p == f"mytickets:active:{tail_offset + len(tail)}" for p in tail_payloads)


def test_caption_reports_the_window(db: Session, contact: Contact):
    for i in range(7):
        _make(db, contact, f"Заявка {i}")
    items, total = messenger_common.my_tickets_page(db, contact, offset=0)
    assert "1–3 из 7" in messenger_common.my_tickets_caption(items, 0, total)


def test_caption_stays_simple_for_a_single_page(db: Session, contact: Contact):
    _make(db, contact, "Единственная")
    items, total = messenger_common.my_tickets_page(db, contact, offset=0)
    assert "Активные: 1" in messenger_common.my_tickets_caption(items, 0, total)
    assert "Единственная" in messenger_common.my_tickets_caption(items, 0, total)


def test_empty_list_has_its_own_caption(db: Session, contact: Contact):
    items, total = messenger_common.my_tickets_page(db, contact, offset=0)
    assert items == [] and total == 0
    assert "Активных заявок нет." in messenger_common.my_tickets_caption(items, 0, total)


def test_search_matches_message_body(db: Session, contact: Contact):
    """Search used to cover only the subject and number, so a ticket whose
    problem was described in the thread (the usual case for email/messenger
    tickets, where the subject is auto-generated) was unfindable."""
    from app.core.enums import MessageDirection
    from app.schemas.message import MessageCreate
    from app.services import messages as messages_service

    ticket = _make(db, contact, "Обращение из MAX")
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="Не открывается VPN-соединение"),
        author_contact=contact,
    )
    found = _search_filter(db.query(Ticket).filter(Ticket.contact_id == contact.id), "VPN").all()
    assert [t.id for t in found] == [ticket.id]


def test_search_returns_each_ticket_once_despite_multiple_matches(db: Session, contact: Contact):
    """Matching the subject AND several messages must not duplicate the row -
    that's why the thread is searched with EXISTS rather than a join."""
    from app.core.enums import MessageDirection
    from app.schemas.message import MessageCreate
    from app.services import messages as messages_service

    ticket = _make(db, contact, "Проблема с принтером")
    for _ in range(3):
        messages_service.add_message(
            db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="принтер всё ещё не работает"),
            author_contact=contact,
        )
    found = _search_filter(db.query(Ticket).filter(Ticket.contact_id == contact.id), "принтер").all()
    assert len(found) == 1
