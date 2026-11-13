"""Customer bot conversations: explicit ticket context and a durable choice inbox."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from app.core.enums import Channel, MessageDirection, OPEN_TICKET_STATUSES, TicketStatus
from app.models.channel_job import ChannelJob
from app.models.channel_conversation_state import ChannelConversationState
from app.models.message import Message
from app.models.messenger_reply import MessengerReply
from app.models.ticket import Ticket

REPLYABLE = OPEN_TICKET_STATUSES | {TicketStatus.RESOLVED}


def account(config):
    return hashlib.sha256(f'{config.base_url}:{config.token}'.encode()).hexdigest()[:20]


def stream(channel, config, chat_id):
    return f'{channel}:{account(config)}:{chat_id}'[:128]


def header(ticket):
    return f'Заявка {ticket.display_number} — {ticket.subject[:200]}\n\n'


def buttons(ticket, existing=None):
    result = list(existing or [])
    if not any(b.get('payload') == f'reply:{ticket.id}' for row in result for b in row):
        result.insert(0, [{'type': 'callback', 'text': 'Ответить по этой заявке', 'payload': f'reply:{ticket.id}'}])
    return result


def remember(db, job, config, recipient, remote_id, message=None):
    """Checkpointed together with each delivered provider part; never for staff alerts."""
    if remote_id is None or job.payload.get('staff_notice') or not job.ticket_id:
        return
    ticket = db.get(Ticket, job.ticket_id)
    if ticket is None:
        return
    contact_id = job.payload.get('contact_id', ticket.contact_id)
    if contact_id != ticket.contact_id:
        return
    state = db.query(ChannelConversationState).filter_by(channel=Channel(job.channel), chat_id=str(recipient), contact_id=contact_id).first()
    # Bot replies without a customer binding do not create routing authority.
    if state is None:
        return
    db.execute(insert(MessengerReply).values(channel=job.channel, account=account(config), chat_id=str(recipient),
        external_message_id=str(remote_id), ticket_id=ticket.id, contact_id=contact_id,
        message_id=message.id if message else None).on_conflict_do_nothing(constraint='uq_messenger_reply'))
    # A visible customer answer selects its ticket for ordinary unquoted replies.
    # Preserve an explicit new-ticket/phone-link flow until a reply button/quote is used.
    if message is not None and not (state.awaiting_new_ticket_text or state.awaiting_revive_text or state.awaiting_phone_confirmation or state.awaiting_ticket_choice):
        state.active_ticket_id = ticket.id
        db.add(state)


def reply_target(db, channel, config, contact, parsed):
    if not parsed.reply_to_mid:
        return None, None
    ref = db.query(MessengerReply).filter_by(channel=channel, account=account(config), chat_id=str(parsed.chat_id),
        external_message_id=str(parsed.reply_to_mid), contact_id=contact.id).first()
    if ref:
        ticket = db.get(Ticket, ref.ticket_id)
        if ticket and ticket.contact_id == contact.id:
            return ticket, ref.message_id
    # Existing replies sent before this release retain their first provider id.
    column = Message.max_message_id if channel == 'max' else Message.telegram_message_id
    parent = db.query(Message).join(Ticket).filter(Ticket.contact_id == contact.id, Message.channel == Channel(channel),
        column == parsed.reply_to_mid).order_by(Message.id.desc()).first()
    return (parent.ticket, parent.id) if parent else (None, None)


def _current(db):
    from app.services.channel_queue import _current
    value = _current.get()
    return db.get(ChannelJob, value[1]) if value else None


def waiting(db, channel, config, state):
    return db.query(ChannelJob).filter_by(kind='inbound', channel=channel, stream_key=stream(channel, config, state.chat_id),
        state='waiting').order_by(ChannelJob.id).with_for_update().all()


def buffer(db, channel, config, state, parsed, module):
    from app.services import attachments
    current = _current(db)
    job = current
    if job is None:
        event_key = f'choice:{channel}:{account(config)}:{parsed.chat_id}:{parsed.mid}'[:255]
        job = db.query(ChannelJob).filter_by(event_key=event_key).first()
        if job is not None:
            return job
        job = ChannelJob(kind='inbound', channel=channel, stream_key=stream(channel, config, state.chat_id),
            event_key=event_key, state='waiting', payload={})
        db.add(job); db.flush()
    if job.payload.get('_sd_pending_message'):
        return job
    files = []
    for source in parsed.attachments:
        name, content, mime = module._attachment_data(config, source)
        item = attachments.store_attachment(0, name, content, mime, staging=True)
        db.info.setdefault('created_files', set()).add(item.stored_path)
        files.append({'path': item.stored_path, 'filename': item.filename, 'mime_type': item.mime_type,
                      'sha256': hashlib.sha256(content).hexdigest()})
    job.payload = {**job.payload, '_sd_pending_message': asdict(replace(parsed, attachments=[])),
        '_sd_pending_files': files, '_sd_summary': (parsed.text or 'Вложения')[:150] + ' · ждёт выбора заявки'}
    job.state, job.ticket_id = 'waiting', None
    if current is not None:
        db.info['waiting_inbound_event'] = True
    state.awaiting_ticket_choice = True
    db.add(state)
    return job


def _append(db, channel, config, ticket, contact, parsed, module):
    message = module._append_message(db, ticket, contact, parsed) if channel == 'max' else module._append_message(db, config, ticket, contact, parsed)
    parent_ticket, parent_id = reply_target(db, channel, config, contact, parsed)
    if parent_ticket and parent_ticket.id == ticket.id and parent_id:
        message.reply_to_message_id = parent_id
    db.add(message)
    return message


def _load_files(job):
    from app.config import settings
    root = (Path(settings.attachments_dir) / '_pending').resolve()
    result = []
    for meta in job.payload.get('_sd_pending_files', []):
        path = Path(meta['path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Недопустимый путь сохранённого вложения')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != meta['sha256']:
            raise ValueError('Сохранённое вложение повреждено')
        result.append((meta['filename'], content, meta.get('mime_type')))
    return result


def _finish_buffer(db, job, message):
    db.info.setdefault('delete_files_after_commit', set()).update(meta['path'] for meta in job.payload.get('_sd_pending_files', []))
    job.payload = {**{k: v for k, v in job.payload.items() if k not in ('_sd_pending_files', '_sd_pending_message')},
                   '_sd_consumed_message_id': message.id}
    job.state, job.ticket_id, job.completed_at = 'processed', message.ticket_id, datetime.now(timezone.utc)
    db.add(job)


def consume(db, channel, config, state, contact, ticket, module):
    from app.services.attachments import store_attachment
    count = 0
    for job in waiting(db, channel, config, state):
        parsed = module.ParsedUpdate(**job.payload['_sd_pending_message'])
        if parsed.external_user_id != state.external_user_id:
            continue
        files = _load_files(job)
        message = _append(db, channel, config, ticket, contact, parsed, module)
        for name, content, mime in files:
            db.add(store_attachment(message.id, name, content, mime))
        message.created_at = job.created_at
        _finish_buffer(db, job, message)
        count += 1
    return count


def create_from_waiting(db, channel, config, state, contact, module, parent_id=None):
    from app.services.attachments import store_attachment
    jobs = waiting(db, channel, config, state)
    if not jobs:
        return None
    first = jobs[0]
    parsed = module.ParsedUpdate(**first.payload['_sd_pending_message'])
    files = _load_files(first)
    ticket = module._create_ticket_from_text(db, config, state, contact, parsed, parent_ticket_id=parent_id)
    message = db.query(Message).filter_by(ticket_id=ticket.id, direction=MessageDirection.INBOUND).order_by(Message.id).first()
    for name, content, mime in files:
        db.add(store_attachment(message.id, name, content, mime))
    message.created_at = first.created_at
    _finish_buffer(db, first, message)
    consume(db, channel, config, state, contact, ticket, module)
    state.awaiting_ticket_choice = state.awaiting_new_ticket_text = state.awaiting_revive_text = False
    db.add(state); db.commit()
    return ticket


def prompt(db, channel, config, state, contact, module, closed=None):
    from app.services.messenger_common import STATUS_LABELS_RU
    candidates = db.query(Ticket).filter(Ticket.contact_id == contact.id, Ticket.status.in_(REPLYABLE)).order_by(Ticket.updated_at.desc(), Ticket.id.desc()).limit(20).all()
    rows = [[{'type': 'callback', 'text': f'{t.display_number} — {t.subject[:35]} ({STATUS_LABELS_RU[t.status]})', 'payload': f'reply:{t.id}'}] for t in candidates]
    if closed:
        rows.append([{'type': 'callback', 'text': f'Продолжить {closed.display_number} новой заявкой', 'payload': f'continue:{closed.id}'}])
    rows.append([{'type': 'callback', 'text': 'Создать новую заявку', 'payload': 'new_ticket'}])
    text = (f'Заявка {closed.display_number} закрыта. ' if closed else '') + ('Сообщение и вложения сохранены. ' if waiting(db, channel, config, state) else '') + 'Выберите, к какой заявке относится ответ, или создайте новую кнопкой ниже.'
    module._send(config, state.chat_id, text, buttons=rows)


def _recover_legacy_selection(db, channel, state, contact):
    # Old deliveries did not update the bot's active ticket (the OH-000003 /
    # OH-000005 incident). Respect any newer explicit customer selection.
    row = db.query(Message, ChannelJob.completed_at).join(Ticket, Message.ticket_id == Ticket.id).join(
        ChannelJob, ChannelJob.message_id == Message.id).filter(
            Ticket.contact_id == contact.id, Message.direction == MessageDirection.OUTBOUND,
            Message.channel == Channel(channel), ChannelJob.channel == channel, ChannelJob.state == 'sent',
            ChannelJob.payload['recipient'].as_string() == str(state.chat_id),
            ChannelJob.payload['ticket_context'].as_boolean().isnot(True)).order_by(ChannelJob.completed_at.desc()).first()
    if row and row[1] and (state.updated_at is None or row[1] > state.updated_at) and state.active_ticket_id != row[0].ticket_id:
        state.active_ticket_id = row[0].ticket_id
        state.updated_at = datetime.now(timezone.utc)
        db.add(state)


def route_text(db, channel, config, state, contact, parsed, module):
    # A native quote is stronger than a previous /new prompt or another active ticket.
    if parsed.reply_to_mid:
        target, _ = reply_target(db, channel, config, contact, parsed)
        if target and TicketStatus(target.status) in REPLYABLE:
            module._cancel_pending_ticket_flow(state)
            state.active_ticket_id = target.id
            state.updated_at = datetime.now(timezone.utc)
            _append(db, channel, config, target, contact, parsed, module)
            db.add(state); db.commit()
            module._acknowledge_gluing(config, parsed.chat_id, target)
            return
        buffer(db, channel, config, state, parsed, module)
        db.commit(); prompt(db, channel, config, state, contact, module, closed=target)
        return
    # Expire abandoned create prompts rather than turning tomorrow's reply into a new task.
    if (state.awaiting_new_ticket_text or state.awaiting_revive_text) and state.updated_at is not None and state.updated_at < datetime.now(timezone.utc) - timedelta(minutes=30):
        module._cancel_pending_ticket_flow(state)
    if state.awaiting_revive_text or state.awaiting_new_ticket_text:
        parent_id = state.revive_parent_ticket_id if state.awaiting_revive_text else None
        module._cancel_pending_ticket_flow(state)
        module._create_ticket_from_text(db, config, state, contact, parsed, parent_ticket_id=parent_id)
        return
    if waiting(db, channel, config, state):
        buffer(db, channel, config, state, parsed, module)
        db.commit(); prompt(db, channel, config, state, contact, module)
        return
    _recover_legacy_selection(db, channel, state, contact)
    active = db.get(Ticket, state.active_ticket_id) if state.active_ticket_id else None
    if active and active.contact_id == contact.id and TicketStatus(active.status) in REPLYABLE:
        _append(db, channel, config, active, contact, parsed, module)
        db.commit(); module._acknowledge_gluing(config, parsed.chat_id, active)
        return
    if active and active.contact_id == contact.id:
        buffer(db, channel, config, state, parsed, module)
        db.commit(); prompt(db, channel, config, state, contact, module, closed=active)
        return
    state.active_ticket_id = None
    candidates = db.query(Ticket).filter(Ticket.contact_id == contact.id, Ticket.status.in_(REPLYABLE)).order_by(Ticket.updated_at.desc(), Ticket.id.desc()).all()
    if len(candidates) == 1:
        target = candidates[0]
        state.active_ticket_id = target.id
        state.awaiting_ticket_choice = False
        _append(db, channel, config, target, contact, parsed, module)
        db.add(state); db.commit(); module._acknowledge_gluing(config, parsed.chat_id, target)
    elif candidates or db.query(Ticket.id).filter_by(contact_id=contact.id).first():
        buffer(db, channel, config, state, parsed, module)
        db.commit(); prompt(db, channel, config, state, contact, module)
    else:
        module._create_ticket_from_text(db, config, state, contact, parsed)


def handle_callback(db, channel, config, state, contact, parsed, module):
    payload = parsed.callback_payload or ''
    if not payload.startswith(('reply:', 'continue:')):
        return False
    try:
        ticket_id = int(payload.split(':', 1)[1])
    except ValueError:
        module._send(config, state.chat_id, 'Заявка не найдена.'); return True
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or ticket.contact_id != contact.id:
        module._send(config, state.chat_id, 'Заявка не найдена.'); return True
    if payload.startswith('continue:'):
        if TicketStatus(ticket.status) in REPLYABLE:
            module._send(config, state.chat_id, 'Заявка ещё открыта. Нажмите «Ответить по этой заявке».'); return True
        if not create_from_waiting(db, channel, config, state, contact, module, ticket.id):
            state.awaiting_revive_text, state.revive_parent_ticket_id = True, ticket.id
            state.updated_at = datetime.now(timezone.utc)
            db.add(state); db.commit()
            module._send(config, state.chat_id, f'Опишите новое обращение — свяжем его с {ticket.display_number}.')
        return True
    if TicketStatus(ticket.status) not in REPLYABLE:
        prompt(db, channel, config, state, contact, module, closed=ticket); return True
    module._cancel_pending_ticket_flow(state)
    state.active_ticket_id = ticket.id
    state.updated_at = datetime.now(timezone.utc)
    consume(db, channel, config, state, contact, ticket, module)
    db.add(state); db.commit()
    module._send(config, state.chat_id, f'Ответ по заявке {ticket.display_number} — {ticket.subject}. Пишите сюда, новая заявка не создаётся.', buttons=buttons(ticket, module._menu_buttons_for(ticket)))
    return True


def cleanup_files(paths):
    for value in paths:
        try:
            Path(value).unlink(missing_ok=True)
        except OSError:
            pass
