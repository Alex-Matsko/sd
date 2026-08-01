"""Pagination across the ticket queue (SD interface) and the bots' "Мои
заявки" list. Both were previously unbounded - the queue returned every
ticket, the bots took a fixed newest-10 window."""

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
    assert len(second) == 2
    assert {t.id for t in items}.isdisjoint({t.id for t in second})


def test_open_tickets_come_first_even_when_older_than_closed_ones(db: Session, contact: Contact):
    """The old implementation took the newest N and only then floated open
    tickets up, so an open ticket older than N closed ones vanished from the
    list entirely - the one the client most likely wanted."""
    old_open = _make(db, contact, "Старая открытая")
    for i in range(6):
        _close(db, _make(db, contact, f"Свежая закрытая {i}"))

    items, total = messenger_common.my_tickets_page(db, contact, offset=0)
    assert total == 7
    assert items[0].id == old_open.id


def test_buttons_offer_next_page_only_when_more_remain(db: Session, contact: Contact):
    for i in range(7):
        _make(db, contact, f"Заявка {i}")

    items, total = messenger_common.my_tickets_page(db, contact, offset=0)
    payloads = [row[0]["payload"] for row in messenger_common.my_tickets_buttons(items, 0, total)]
    assert f"mytickets:{messenger_common.MY_TICKETS_PAGE_SIZE}" in payloads
    assert not any(p == "mytickets:0" for p in payloads)  # no "back" on the first page

    tail, _ = messenger_common.my_tickets_page(db, contact, offset=messenger_common.MY_TICKETS_PAGE_SIZE)
    tail_payloads = [row[0]["payload"] for row in messenger_common.my_tickets_buttons(tail, 5, total)]
    assert "mytickets:0" in tail_payloads  # back to the first page
    assert not any(p.startswith("mytickets:10") for p in tail_payloads)  # nothing beyond the end


def test_caption_reports_the_window(db: Session, contact: Contact):
    for i in range(7):
        _make(db, contact, f"Заявка {i}")
    items, total = messenger_common.my_tickets_page(db, contact, offset=0)
    assert "1–5 из 7" in messenger_common.my_tickets_caption(items, 0, total)


def test_caption_stays_simple_for_a_single_page(db: Session, contact: Contact):
    _make(db, contact, "Единственная")
    items, total = messenger_common.my_tickets_page(db, contact, offset=0)
    assert messenger_common.my_tickets_caption(items, 0, total) == "Ваши заявки (открытых: 1 из 1):"


def test_empty_list_has_its_own_caption(db: Session, contact: Contact):
    items, total = messenger_common.my_tickets_page(db, contact, offset=0)
    assert items == [] and total == 0
    assert messenger_common.my_tickets_caption(items, 0, total) == "У вас пока нет заявок."
