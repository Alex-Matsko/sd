"""A published result is distinct from both a status and customer acceptance."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.enums import MessageDirection, TicketStatus
from app.models.channel_job import ChannelJob
from app.models.message import Message
from app.models.ticket import Ticket
from app.services import audit, customer_delivery, messages, tickets


def submit(db, ticket, payload, actor, files):
    from app.services.channel_queue import DeferredCommitSession
    from app.services.messenger_dialog import cleanup_files
    from app.services.message_content import prepare
    payload = prepare(payload, files)
    if payload.direction != MessageDirection.OUTBOUND or not payload.body.strip() or not payload.request_id:
        raise ValueError('Опишите результат и где его проверить. Для отправки нужен идентификатор запроса.')
    customer_delivery.validate_reply(db, ticket, payload)
    unit = DeferredCommitSession(bind=db.connection(), join_transaction_mode='create_savepoint')
    try:
        with unit:
            current = unit.query(Ticket).filter_by(id=ticket.id).with_for_update().one()
            previous = unit.query(Message).filter_by(request_key=f'u:{actor.id}:{payload.request_id}').first()
            if previous is not None:
                if current.resolution_message_id != previous.id:
                    raise messages.RequestConflict('Этот запрос уже использован для другого действия')
                messages.add_message(unit, current, payload, author_user=actor, attachments=files)
            else:
                if current.status not in (TicketStatus.IN_PROGRESS, TicketStatus.CLOSED):
                    raise ValueError('Передать результат можно из работы. Верните заявку в работу для новой версии.')
                result = messages.add_message(unit, current, payload, author_user=actor, attachments=files)
                current.resolution_message_id, current.accepted_at = result.id, None
                if current.status == TicketStatus.CLOSED:
                    _reopen(unit, current, actor.id, 'result_republished')
                tickets.transition_status(unit, current, TicketStatus.RESOLVED, actor, notify_status=False)
                audit.record(unit, entity_type='ticket', entity_id=current.id, action='result_published',
                             user_id=actor.id, changes={'message_id': result.id, 'channel': result.channel.value})
                from app.services import staff_notifications
                staff_notifications.notify_status_change(unit, current, TicketStatus.RESOLVED)
            Session.commit(unit)
        db.commit()
    except Exception:
        db.rollback()
        cleanup_files(unit.info.get('created_files', set()))
        raise
    db.refresh(ticket)
    return ticket


def _reopen(db, ticket, user_id, reason):
    old = ticket.status
    ticket.status, ticket.closed_at, ticket.accepted_at = TicketStatus.IN_PROGRESS, None, None
    ticket.reopen_count = (ticket.reopen_count or 0) + 1
    db.add(ticket)
    audit.record(db, entity_type='ticket', entity_id=ticket.id, action='status_changed', user_id=user_id,
                 changes={'from': old.value, 'to': 'in_progress', 'reason': reason})


def decide(db, ticket, contact, version, accept):
    ticket = db.query(Ticket).filter_by(id=ticket.id).populate_existing().with_for_update().one()
    if ticket.contact_id != contact.id:
        raise ValueError('Заявка не найдена')
    if (ticket.resolution_message_id or 0) != version:
        raise ValueError('Это предыдущая версия результата. Нажмите «Посмотреть результат» и проверьте актуальную.')
    if accept:
        if not version:
            raise ValueError('Результат ещё не опубликован. Напишите сотруднику по этой заявке.')
        if ticket.accepted_at and ticket.status == TicketStatus.CLOSED:
            return 'Результат уже принят вами. Спасибо!'
        if ticket.status != TicketStatus.RESOLVED:
            raise ValueError('Заявка уже вернулась в работу. Дождитесь нового результата.')
        ticket.accepted_at = datetime.now(timezone.utc)
        audit.record(db, entity_type='ticket', entity_id=ticket.id, action='customer_accepted', user_id=None,
                     changes={'contact_id': contact.id, 'message_id': version})
        tickets.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)
        return 'Результат принят. Заявка закрыта. Спасибо! Уточнения можно писать сюда.'
    if ticket.status == TicketStatus.CLOSED:
        _reopen(db, ticket, None, 'customer_rework')
        from app.services import staff_notifications
        staff_notifications.notify_status_change(db, ticket, TicketStatus.IN_PROGRESS)
    elif ticket.status == TicketStatus.RESOLVED:
        tickets.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    elif ticket.status != TicketStatus.IN_PROGRESS:
        raise ValueError('Сейчас заявку нельзя вернуть на доработку')
    audit.record(db, entity_type='ticket', entity_id=ticket.id, action='customer_requested_rework', user_id=None,
                 changes={'contact_id': contact.id, 'message_id': version})
    db.add(ticket); db.commit()
    return 'Заявка возвращена в работу. Напишите сюда замечания и приложите файлы, если нужны. Новая заявка не создаётся.'


def result_buttons(ticket):
    if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        return []
    rows = [[{'type': 'callback', 'text': 'Посмотреть результат', 'payload': f'result:{ticket.id}'}]]
    if ticket.status == TicketStatus.RESOLVED and ticket.resolution_message_id:
        rows.append([{'type': 'callback', 'text': 'Принять результат', 'payload': f'accept:{ticket.id}:{ticket.resolution_message_id}'}])
    rows.append([{'type': 'callback', 'text': 'Нужна доработка', 'payload': f'rework:{ticket.id}:{ticket.resolution_message_id or 0}'}])
    return rows


def replay(db, channel, state, ticket):
    message = db.get(Message, ticket.resolution_message_id) if ticket.resolution_message_id else None
    if message is None or message.ticket_id != ticket.id or message.direction != MessageDirection.OUTBOUND:
        return False
    db.add(ChannelJob(kind='outbound', channel=channel, event_key=f'result:{uuid4().hex}',
        stream_key=f'{channel}:chat:{state.chat_id}', ticket_id=ticket.id,
        payload={'result_message_id': message.id, 'ticket_context': True, 'recipient': state.chat_id,
                 'contact_id': ticket.contact_id, 'organization_id': ticket.organization_id,
                 'attachment_ids': [a.id for a in message.attachments], '_sd_summary': 'Повтор результата по запросу клиента'}))
    db.commit()
    return True


def handle_callback(db, channel, config, state, contact, parsed, module):
    payload = parsed.callback_payload or ''
    if not payload.startswith(('result:', 'accept:', 'rework:')):
        return False
    from app.services.messenger_dialog import buttons as dialog_buttons
    try:
        parts = payload.split(':'); ticket = db.get(Ticket, int(parts[1]))
        if ticket is None or ticket.contact_id != contact.id:
            raise ValueError('Заявка не найдена')
        if parts[0] == 'result':
            if not replay(db, channel, state, ticket):
                module._send(config, state.chat_id, f'{ticket.display_number} — {ticket.subject}. Результат ещё не опубликован сотрудником. Нажмите «Ответить по этой заявке», чтобы запросить его.',
                             buttons=dialog_buttons(ticket))
            return True
        if len(parts) != 3:
            raise ValueError('Некорректная кнопка')
        if parts[0] == 'accept' and ticket.resolution_message_id:
            original = db.query(ChannelJob).filter_by(message_id=ticket.resolution_message_id).first()
            if original and original.channel == channel and original.state != 'sent':
                raise ValueError('Результат и файлы ещё отправляются. Дождитесь завершения доставки и повторите приёмку.')
        text = decide(db, ticket, contact, int(parts[2]), parts[0] == 'accept')
        module._cancel_pending_ticket_flow(state)
        state.active_ticket_id, state.updated_at = ticket.id, datetime.now(timezone.utc)
        db.add(state); db.commit()
        from app.services.messenger_dialog import buttons
        module._send(config, state.chat_id, f'{ticket.display_number} — {ticket.subject}\n\n{text}', buttons=buttons(ticket))
    except (ValueError, IndexError) as exc:
        module._send(config, state.chat_id, str(exc) if isinstance(exc, ValueError) else 'Некорректная кнопка')
    return True
