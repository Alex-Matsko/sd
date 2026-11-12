# coding: utf-8
from types import SimpleNamespace

import pytest

from app.core.enums import Channel, TicketStatus, TicketType
from app.models.channel_job import ChannelJob
from app.models.user import User
from app.core.enums import UserRole
from app.schemas.ticket import TicketCreate
from app.services import tickets, staff_notifications, max_channel, telegram_channel, messenger_common


@pytest.fixture(autouse=True)
def fake_channels(monkeypatch):
    monkeypatch.setattr(max_channel, 'load_max_config', lambda db: SimpleNamespace())
    monkeypatch.setattr(telegram_channel, 'load_telegram_config', lambda db: SimpleNamespace())
    monkeypatch.setattr('app.config.settings.staff_base_url', 'https://service.o-horizons.com')
    monkeypatch.setattr('app.config.settings.portal_base_url', 'https://service.o-horizons.com/portal')


def test_both_staff_channels_have_identical_cards_and_completion(db, contact, engineer_user):
    admin = db.query(User).filter_by(role=UserRole.ADMIN).first()
    admin.telegram_id, admin.max_id, admin.max_chat_id = 'tg-admin', 'max-admin', 'chat-admin'
    admin.telegram_notification_scope = admin.max_notification_scope = 'all'
    admin.max_notify_new_tickets = True
    engineer_user.telegram_id, engineer_user.max_id, engineer_user.max_chat_id = 'tg-owner', 'max-owner', 'chat-owner'
    engineer_user.telegram_notification_scope = engineer_user.max_notification_scope = 'assigned'
    engineer_user.max_notify_new_tickets = True
    db.commit()
    ticket = tickets.create_ticket(db, TicketCreate(contact_id=contact.id, channel=Channel.PORTAL,
        type=TicketType.INCIDENT, manual_priority="P3", manual_priority_reason="test", subject='Проверка карточек'), actor=None)
    first = db.query(ChannelJob).filter_by(ticket_id=ticket.id).all()
    assert len(first) == 2
    assert first[0].payload['text'] == first[1].payload['text']
    assert 'Статус: Новая' in first[0].payload['text']
    assert {j.payload['staff_user_id'] for j in first} == {admin.id}
    ticket.assigned_engineer_id = engineer_user.id
    db.commit()
    tickets.transition_status(db, ticket, TicketStatus.IN_PROGRESS, None)
    tickets.transition_status(db, ticket, TicketStatus.RESOLVED, None)
    for status, heading in [('Решена', 'Работы завершены')]:
        jobs = db.query(ChannelJob).filter_by(ticket_id=ticket.id).all()
        matches = [j for j in jobs if j.payload['text'].startswith(heading)]
        assert len(matches) == 4
        assert len({j.payload['text'] for j in matches}) == 1
        assert f'Статус: {status}' in matches[0].payload['text']
        assert f'https://service.o-horizons.com/tickets/{ticket.id}' in matches[0].payload['text']
    tickets.transition_status(db, ticket, TicketStatus.CLOSED, None)
    assert len([j for j in db.query(ChannelJob).filter_by(ticket_id=ticket.id) if j.payload['text'].startswith('Заявка закрыта')]) == 4


@pytest.mark.parametrize('channel,module', [(Channel.MAX, max_channel), (Channel.TELEGRAM, telegram_channel)])
def test_client_close_has_one_final_card_and_portal_link(db, contact, monkeypatch, channel, module):
    monkeypatch.setattr(module, '_find_chat_state', lambda db, contact_id: SimpleNamespace(chat_id='customer-chat'))
    ticket = tickets.create_ticket(db, TicketCreate(contact_id=contact.id, channel=channel,
        type=TicketType.INCIDENT, manual_priority="P3", manual_priority_reason="test", subject='Проверка закрытия'), actor=None)
    messenger_common.close_ticket_chain(db, ticket)
    jobs = db.query(ChannelJob).filter_by(ticket_id=ticket.id, channel=channel.value).all()
    assert len(jobs) == 1
    text = jobs[0].payload['text']
    assert text.startswith('Заявка закрыта') and 'Статус: Закрыта' in text
    assert f'https://service.o-horizons.com/portal?ticket={ticket.id}' in text
    assert '/tickets/' not in text and '1 до 5' in text
    assert len(jobs[0].payload['buttons'][0]) == 5
