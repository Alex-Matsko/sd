"""Cross-channel identity matching (по запросу заказчика): normalizing/
matching phone numbers across Contact records, and merging two Contacts
that turned out to be the same person - shared by both max_channel.py and
telegram_channel.py's opt-in "связать телефон" flow, and by the dispatcher-
facing POST /contacts/{id}/merge endpoint."""

from app.core.enums import Channel, MessageDirection, Priority, TicketStatus, TicketType
from app.models.channel_conversation_state import ChannelConversationState
from app.models.contact import Contact, ContactEmail, ContactPhone
from app.models.message import Message
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import messages as messages_service
from app.services import messenger_common
from app.services import tickets as tickets_service


def test_normalize_phone_digits_ignores_formatting():
    assert messenger_common.normalize_phone_digits("+7 (916) 123-45-67") == "9161234567"
    assert messenger_common.normalize_phone_digits("89161234567") == "9161234567"
    assert messenger_common.normalize_phone_digits("79161234567") == "9161234567"


def test_normalize_phone_digits_too_short_returns_empty():
    assert messenger_common.normalize_phone_digits("12345") == ""


def test_find_contact_by_phone_matches_regardless_of_format(db, contact):
    db.add(ContactPhone(contact_id=contact.id, phone="+7 916 123-45-67", is_primary=True))
    db.commit()

    found = messenger_common.find_contact_by_phone(db, "89161234567")
    assert found is not None
    assert found.id == contact.id


def test_find_contact_by_phone_no_match_returns_none(db, contact):
    db.add(ContactPhone(contact_id=contact.id, phone="+79161234567", is_primary=True))
    db.commit()

    assert messenger_common.find_contact_by_phone(db, "+79997654321") is None


def test_merge_contacts_moves_tickets_and_messages(db, contact, organization):
    duplicate = Contact(organization_id=organization.id, full_name="Дубликат", max_id="max-dup", is_confirmed=False)
    db.add(duplicate)
    db.commit()

    payload = TicketCreate(
        contact_id=duplicate.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Заявка дубликата",
        manual_priority=Priority.P3, manual_priority_reason="test",
    )
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    message = messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="привет"), author_contact=duplicate
    )
    duplicate_id = duplicate.id

    messenger_common.merge_contacts(db, from_contact=duplicate, into_contact=contact)

    db.refresh(ticket)
    db.refresh(message)
    assert ticket.contact_id == contact.id
    assert message.author_contact_id == contact.id
    assert db.get(Contact, duplicate_id) is None
    db.refresh(contact)
    assert contact.max_id == "max-dup"


def test_merge_contacts_moves_channel_conversation_state(db, contact, organization):
    duplicate = Contact(organization_id=organization.id, full_name="Дубликат", telegram_id="tg-dup", is_confirmed=False)
    db.add(duplicate)
    db.commit()
    state = ChannelConversationState(channel=Channel.TELEGRAM, external_user_id="tg-dup", chat_id="c1", contact_id=duplicate.id)
    db.add(state)
    db.commit()

    messenger_common.merge_contacts(db, from_contact=duplicate, into_contact=contact)

    db.refresh(state)
    assert state.contact_id == contact.id


def test_merge_contacts_does_not_clobber_existing_channel_id(db, contact, organization):
    contact.telegram_id = "tg-original"
    db.commit()
    duplicate = Contact(organization_id=organization.id, full_name="Дубликат", telegram_id="tg-dup", is_confirmed=False)
    db.add(duplicate)
    db.commit()

    messenger_common.merge_contacts(db, from_contact=duplicate, into_contact=contact)

    db.refresh(contact)
    assert contact.telegram_id == "tg-original"


def test_merge_contacts_moves_phone_and_email(db, contact, organization):
    # ContactPhone.phone and ContactEmail.email are globally unique, so two
    # Contacts can never hold the literal same value at once - the merge is
    # normally reached via find_contact_by_phone matching on exactly this
    # value, which is why the duplicate's own copy needs dropping rather
    # than moved (see merge_contacts' existing_phones/existing_emails guard).
    duplicate = Contact(organization_id=organization.id, full_name="Дубликат", is_confirmed=False)
    db.add(duplicate)
    db.commit()
    db.add(ContactPhone(contact_id=duplicate.id, phone="+79161234567", is_primary=True))
    db.add(ContactEmail(contact_id=duplicate.id, email="dup@example.com", is_primary=True))
    db.commit()

    messenger_common.merge_contacts(db, from_contact=duplicate, into_contact=contact)

    db.refresh(contact)
    assert contact.phones[0].phone == "+79161234567"
    assert contact.emails[0].email == "dup@example.com"
