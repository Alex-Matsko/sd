"""Customer commitments required when staff accepts work; estimates never book actual time."""
from datetime import datetime, timezone
from app.core.enums import Channel
from app.services import audit


def require_plan(ticket, *, future=True):
    if ticket.planned_due_at is None or not ticket.estimated_minutes or ticket.estimated_minutes < 1:
        raise ValueError('Перед началом работы укажите срок выполнения и примерные трудозатраты больше нуля.')
    if future and ticket.planned_due_at <= datetime.now(timezone.utc):
        raise ValueError('Срок выполнения уже прошёл. Укажите новый срок перед началом работы.')


def apply(db, ticket, payload, actor):
    changed = {}
    for field in ('planned_due_at', 'estimated_minutes'):
        if field in payload.model_fields_set and getattr(payload, field) != getattr(ticket, field):
            before, after = getattr(ticket, field), getattr(payload, field)
            changed[field] = {'from': before.isoformat() if isinstance(before, datetime) else before,
                              'to': after.isoformat() if isinstance(after, datetime) else after}
            setattr(ticket, field, after)
    if changed:
        db.add(ticket)
        audit.record(db, entity_type='ticket', entity_id=ticket.id, action='updated', user_id=actor.id if actor else None, changes=changed)
    return bool(changed)


def notify_plan(db, ticket):
    from app.services import customer_delivery, max_channel, telegram_channel, email_channel
    from app.services.channel_queue import enqueue_notification
    from app.services.ticket_messages import ticket_notice
    channel = customer_delivery.preferred_channel(db, ticket)
    body = ticket_notice(ticket, 'План выполнения заявки обновлён', client=True)
    if channel in (Channel.MAX, Channel.TELEGRAM):
        module = max_channel if channel == Channel.MAX else telegram_channel
        config = module.load_max_config(db) if channel == Channel.MAX else module.load_telegram_config(db)
        state = module._find_chat_state(db, ticket.contact_id)
        if config and state:
            enqueue_notification(db, channel.value, state.chat_id, body, ticket=ticket)
    elif channel == Channel.EMAIL and email_channel.load_email_config(db):
        emails = ticket.contact.emails
        recipient = next((e.email for e in emails if e.is_primary), emails[0].email if emails else None)
        if recipient:
            enqueue_notification(db, 'email', recipient, body, ticket=ticket)
