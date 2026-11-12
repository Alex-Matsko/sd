"""Transport execution and per-part checkpoints for the durable outbox."""
from datetime import timedelta
from pathlib import Path
import uuid

from app.core.enums import Channel, MessageDirection
from app.models.message import Message
from app.models.ticket import Ticket
from app.services import email_channel, max_channel, max_client, sla, telegram_channel, telegram_client
from app.services.channel_queue import ChannelFailure, PermanentChannelFailure, LEASE_SECONDS, now


def _checkpoint(db, job, **changes):
    job.payload = {**job.payload, **changes}
    job.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
    db.commit()
    # Reacquire the row after the checkpoint. A valid lease prevents another
    # worker taking it during the short interval between these transactions.
    db.refresh(job, with_for_update=True)


def _first_response(db, message):
    if message is not None and message.ticket.first_response_at is None:
        sla.register_first_response(message.ticket, now())
        db.add(message.ticket)


def _file(attachment):
    path = Path(attachment.stored_path)
    if not path.is_file():
        raise PermanentChannelFailure(f"Файл «{attachment.filename}» отсутствует в хранилище")
    return attachment.filename, path.read_bytes(), attachment.mime_type or "application/octet-stream"


def send_job(db, job):
    message = db.get(Message, job.message_id) if job.message_id else None
    if job.message_id and message is None:
        raise PermanentChannelFailure("Сообщение удалено")
    if message is not None and message.direction != MessageDirection.OUTBOUND:
        raise PermanentChannelFailure("Внутренняя заметка не может быть отправлена клиенту")
    payload = job.payload
    ticket = message.ticket if message else db.get(Ticket, job.ticket_id) if job.ticket_id else None
    if ticket and payload.get("contact_id") is not None and (ticket.contact_id != payload.get("contact_id")
                    or ticket.organization_id != payload.get("organization_id")):
        raise PermanentChannelFailure("Клиент заявки изменён. Проверьте получателя и создайте новый ответ.")
    if payload.get("staff_notice"):
        from app.models.user import User
        from app.services import staff_notifications, ticket_access
        user = db.get(User, payload.get("staff_user_id"))
        if user is None or not user.is_active or ticket is None or not ticket_access.can_see(db, user, ticket):
            return False
        if job.channel == "telegram":
            if user.telegram_id != payload.get("recipient") or not staff_notifications.telegram_allowed(db, user, ticket):
                return False
        elif (not user.max_notify_new_tickets or user.max_id != payload.get("staff_max_id") or
              user.max_chat_id != payload.get("recipient") or
              (not ticket_access.sees_full_queue(user) and ticket.assigned_engineer_id != user.id)):
            return False
    module = {"email": email_channel, "max": max_channel, "telegram": telegram_channel}[job.channel]
    if job.channel == "email":
        config = email_channel.load_email_config(db)
    elif job.channel == "max":
        config = max_channel.load_max_config(db)
    else:
        config = telegram_channel.load_telegram_config(db)
    if config is None:
        raise ChannelFailure("Канал отключён или не настроен")
    recipient = payload.get("recipient")
    if not recipient and message:
        if job.channel == "email":
            emails = message.ticket.contact.emails
            recipient = next((e.email for e in emails if e.is_primary), emails[0].email if emails else None)
        else:
            state = module._find_chat_state(db, message.ticket.contact_id)
            recipient = state.chat_id if state else None
        if recipient:
            _checkpoint(db, job, recipient=recipient)
    if not recipient:
        raise PermanentChannelFailure("Не найден адрес или чат получателя")
    attachments = list(message.attachments) if message else []
    attachment_ids = payload.get("attachment_ids")
    if attachment_ids is not None:
        attachments = [item for item in attachments if item.id in attachment_ids]
        if len(attachments) != len(attachment_ids):
            raise PermanentChannelFailure("Состав вложений изменён. Проверьте сообщение.")
    text = message.body if message else payload.get("text", "")
    if job.channel == "email":
        if ticket is None:
            raise PermanentChannelFailure("Письмо не связано с заявкой")
        stable_id = job.payload.get("email_message_id")
        if not stable_id:
            stable_id = f"<sd-{uuid.uuid4().hex}@{config.from_address.rsplit('@', 1)[-1]}>"
            _checkpoint(db, job, email_message_id=stable_id)
        parent = db.get(Message, message.reply_to_message_id) if message and message.reply_to_message_id else None
        if not parent or not parent.email_message_id:
            parent = db.query(Message).filter(Message.ticket_id == ticket.id, Message.id != (message.id if message else -1),
                                             Message.email_message_id.isnot(None)).order_by(Message.id.desc()).first()
        rich_options = {"content_blocks": message.content_blocks, "attachment_ids": [a.id for a in attachments]} if message and message.content_blocks is not None else {}
        email_channel.send_outbound_email(config, recipient, ticket, text,
                                          parent.email_message_id if parent else None,
                                          attachments=[_file(item) for item in attachments], message_id=stable_id, **rich_options)
        if message:
            message.email_message_id = stable_id
        _first_response(db, message)
        return
    parent = db.get(Message, message.reply_to_message_id) if message and message.reply_to_message_id else None
    reply = (parent.max_message_id if job.channel == "max" else parent.telegram_message_id) if parent else payload.get("reply_to")
    buttons = payload.get("buttons") if message is None else (
        max_channel._menu_buttons_for(message.ticket) if job.channel == "max" else telegram_channel._close_button_for(message.ticket))
    if message is not None and message.content_blocks is not None:
        _send_rich_parts(db, job, message, config, recipient, attachments, reply, buttons)
        return
    chunks = [text[index:index + 3000] for index in range(0, len(text), 3000)]
    done = job.payload.get("text_chunks_sent", 0)
    for index in range(done, len(chunks)):
        if job.channel == "max":
            result = max_client.send_message(config.base_url, config.token, recipient, chunks[index],
                                             buttons=buttons if index == 0 else None, reply_to_mid=reply if index == 0 else None)
            remote_id = ((result.get("message") or {}).get("body") or {}).get("mid")
            if not remote_id:
                raise ChannelFailure("MAX не подтвердил отправку сообщения")
            if message and index == 0:
                message.max_message_id = remote_id
        else:
            result = telegram_client.send_message(config.base_url, config.token, recipient, chunks[index],
                                                  buttons=buttons if index == 0 else None,
                                                  reply_to_message_id=reply if index == 0 else None)
            remote_id = result.get("message_id")
            if remote_id is None:
                raise ChannelFailure("Telegram не подтвердил отправку сообщения")
            if message and index == 0:
                message.telegram_message_id = remote_id
        _first_response(db, message)
        _checkpoint(db, job, text_chunks_sent=index + 1)
    sent = list(job.payload.get("sent_attachment_ids", []))
    for attachment in attachments:
        if attachment.id in sent:
            continue
        filename, content, mime = _file(attachment)
        if job.channel == "telegram":
            result = telegram_client.send_document(config.base_url, config.token, recipient, filename, content, mime)
            if result.get("message_id") is None:
                raise ChannelFailure("Telegram не подтвердил отправку файла")
        else:
            tokens = dict(job.payload.get("max_file_tokens", {}))
            token = tokens.get(str(attachment.id))
            if not token:
                token = max_client.upload_file(config.base_url, config.token, filename, content, mime)
                tokens[str(attachment.id)] = token
                _checkpoint(db, job, max_file_tokens=tokens)
            result = max_client.send_message(config.base_url, config.token, recipient, filename,
                                             attachments=[{"type": "file", "payload": {"token": token}}])
            if not ((result.get("message") or {}).get("body") or {}).get("mid"):
                raise ChannelFailure("MAX не подтвердил отправку файла")
        sent.append(attachment.id)
        _first_response(db, message)
        _checkpoint(db, job, sent_attachment_ids=sent)
    if not chunks and not attachments:
        raise PermanentChannelFailure("Сообщение пустое")


def _send_rich_parts(db, job, message, config, recipient, attachments, reply, buttons):
    from app.services.message_content import delivery_parts, MessageContentError
    try:
        parts = delivery_parts(message, attachments)
    except MessageContentError as exc:
        raise PermanentChannelFailure(str(exc))
    if not parts:
        raise PermanentChannelFailure("Сообщение пустое")
    for index in range(job.payload.get("content_parts_sent", 0), len(parts)):
        kind, value = parts[index]
        if kind == "text":
            if job.channel == "telegram":
                result = telegram_client.send_message(config.base_url, config.token, recipient, value,
                    buttons=buttons if index == 0 else None, reply_to_message_id=reply if index == 0 else None)
            else:
                result = max_client.send_message(config.base_url, config.token, recipient, value,
                    buttons=buttons if index == 0 else None, reply_to_mid=reply if index == 0 else None)
        else:
            filename, content, mime = _file(value)
            if job.channel == "telegram":
                # Documents preserve original bytes and resolution; sendPhoto recompresses images.
                result = telegram_client.send_document(config.base_url, config.token, recipient, filename, content, mime)
            else:
                tokens = dict(job.payload.get("max_file_tokens", {}))
                token = tokens.get(str(value.id))
                if not token:
                    token = max_client.upload_file(config.base_url, config.token, filename, content, mime)
                    tokens[str(value.id)] = token
                    _checkpoint(db, job, max_file_tokens=tokens)
                result = max_client.send_message(config.base_url, config.token, recipient, filename,
                    attachments=[{"type": "file", "payload": {"token": token}}])
        remote_id = result.get("message_id") if job.channel == "telegram" else ((result.get("message") or {}).get("body") or {}).get("mid")
        if remote_id is None:
            raise ChannelFailure("Канал не подтвердил отправку части сообщения")
        if index == 0:
            if job.channel == "telegram":
                message.telegram_message_id = remote_id
            else:
                message.max_message_id = remote_id
        _first_response(db, message)
        _checkpoint(db, job, content_parts_sent=index + 1)
