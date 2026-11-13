"""Ticket source and customer delivery destination are separate choices."""
from sqlalchemy import or_
from app.core.enums import Channel, MessageDirection
from app.models.message import Message


class CustomerDeliveryError(ValueError):
    pass


def preferred_channel(db, ticket):
    latest = db.query(Message.channel).filter(Message.ticket_id == ticket.id,
        Message.direction == MessageDirection.OUTBOUND,
        or_(Message.request_key.is_(None), Message.request_key.notlike('automation:%')),
        Message.channel.in_([Channel.MAX, Channel.TELEGRAM, Channel.EMAIL, Channel.PORTAL])).order_by(Message.id.desc()).first()
    return latest[0] if latest else ticket.channel


def destinations(db, ticket):
    from app.services import email_channel, max_channel, telegram_channel
    contact = ticket.contact
    result = []
    for channel, module, loader in [(Channel.MAX, max_channel, max_channel.load_max_config),
                                    (Channel.TELEGRAM, telegram_channel, telegram_channel.load_telegram_config)]:
        state = module._find_chat_state(db, ticket.contact_id)
        configured = loader(db) is not None
        linked = bool(state and state.chat_id and str(getattr(contact, channel.value + '_id')) == state.external_user_id)
        result.append({'channel': channel.value, 'available': configured and linked,
            'destination': contact.full_name if linked else None,
            'reason': None if configured and linked else 'Канал отключён или не настроен' if not configured else 'Клиент ещё не связал этот контакт с ботом'})
    email = next((e.email for e in contact.emails if e.is_primary), contact.emails[0].email if contact.emails else None)
    configured = email_channel.load_email_config(db) is not None
    result.append({'channel': 'email', 'available': bool(email and configured), 'destination': email,
        'reason': None if email and configured else 'У контакта не указан email' if not email else 'Почтовый канал не настроен'})
    result.append({'channel': 'portal', 'available': True, 'destination': 'Личный кабинет',
        'reason': 'Сообщение сохранится в кабинете. Уведомление в мессенджер или на почту не отправляется.'})
    preferred = preferred_channel(db, ticket)
    default = preferred.value if any(row['channel'] == preferred.value and row['available'] for row in result) else None
    return {'source_channel': ticket.channel.value, 'default_channel': default, 'options': result}


def validate_reply(db, ticket, payload):
    if payload.direction != MessageDirection.OUTBOUND:
        return
    channel = payload.channel or ticket.channel
    if channel not in (Channel.MAX, Channel.TELEGRAM, Channel.EMAIL, Channel.PORTAL):
        raise CustomerDeliveryError('Выберите канал ответа клиенту. «Телефон» — источник заявки; сообщение по телефону не отправляется.')
    option = next(row for row in destinations(db, ticket)['options'] if row['channel'] == channel.value)
    if not option['available']:
        raise CustomerDeliveryError(option['reason'])
