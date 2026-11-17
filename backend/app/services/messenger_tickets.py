"""The same customer ticket list and full card in MAX and Telegram."""
from datetime import datetime, timezone

from app.core.enums import MessageDirection, TicketStatus
from app.models.message import Message
from app.models.ticket import Ticket
from app.services import messenger_common as common

DESCRIPTION_PAGE_SIZE = 1000


def send_navigation(config, chat_id, module, text, buttons):
    from app.services.channel_queue import defer_bot_reply
    channel = 'max' if module.__name__.endswith('max_channel') else 'telegram'
    if not defer_bot_reply(channel, chat_id, text, buttons, suppress_ticket_buttons=True):
        module._send(config, chat_id, text, buttons=buttons)


def send_list(db, config, contact, chat_id, module, offset=0, scope='active'):
    counts = common.my_tickets_counts(db, contact)
    total = counts[scope]
    last_page = max(0, (total - 1) // common.MY_TICKETS_PAGE_SIZE) * common.MY_TICKETS_PAGE_SIZE
    offset = min(max(0, offset) // common.MY_TICKETS_PAGE_SIZE * common.MY_TICKETS_PAGE_SIZE, last_page)
    items, total = common.my_tickets_page(db, contact, offset, scope)
    send_navigation(config, chat_id, module, common.my_tickets_caption(items, offset, total, scope, counts),
               common.my_tickets_buttons(items, offset, total, scope, counts))


def _select(db, channel, state, contact, ticket, config, module):
    from app.services import messenger_dialog as dialog
    module._cancel_pending_ticket_flow(state)
    state.active_ticket_id, state.updated_at = ticket.id, datetime.now(timezone.utc)
    if TicketStatus(ticket.status) in dialog.REPLYABLE:
        dialog.consume(db, channel, config, state, contact, ticket, module)
    db.add(state); db.commit()


def _card(db, ticket, module):
    from app.services import messenger_dialog as dialog
    status = TicketStatus(ticket.status)
    detail = common.ticket_stage(ticket)
    if status == TicketStatus.CLOSED and not ticket.resolution_message_id:
        detail += ' Результат отдельно не опубликован сотрудником. Его можно запросить по кнопке ответа.'
    detail += ('\nДля нового вопроса нажмите «Создать связанное обращение».' if status == TicketStatus.CANCELLED else '\nПишите сюда по этой заявке — новая заявка не создаётся.')
    rows = [[{'type': 'callback', 'text': 'Описание заявки полностью', 'payload': f'ticketbody:{ticket.id}:0'}]]
    rows.extend(module._menu_buttons_for(ticket))
    return common.ticket_notice(ticket, 'Карточка заявки', client=True, detail=detail), dialog.buttons(ticket, rows)


def handle_callback(db, channel, config, state, contact, parsed, module):
    payload = parsed.callback_payload or ''
    if payload == 'cmd:my_tickets' or payload.startswith('mytickets:'):
        try:
            if payload == 'cmd:my_tickets':
                scope, offset = 'active', 0
            else:
                parts = payload.split(':')
                # Older messages carry mytickets:<offset>; keep those buttons usable.
                scope, offset = ('active', int(parts[1])) if len(parts) == 2 else (parts[1], int(parts[2]))
                if len(parts) not in (2, 3) or scope not in common.TICKET_SCOPES or offset < 0:
                    raise ValueError('Invalid list')
        except (ValueError, IndexError):
            send_navigation(config, parsed.chat_id, module, 'Список изменился. Нажмите «Мои заявки» ещё раз.', module._main_menu_buttons())
            return True
        module._cancel_pending_ticket_flow(state)
        db.add(state); db.commit()
        send_list(db, config, contact, parsed.chat_id, module, offset, scope)
        return True
    if not payload.startswith(('ticket:', 'ticketbody:')):
        return False
    try:
        parts = payload.split(':')
        ticket = db.get(Ticket, int(parts[1]))
        if ticket is None or ticket.contact_id != contact.id:
            raise ValueError('Заявка не найдена.')
        if parts[0] == 'ticket':
            if len(parts) != 2:
                raise ValueError('Заявка не найдена.')
            _select(db, channel, state, contact, ticket, config, module)
            text, rows = _card(db, ticket, module)
            module._send(config, parsed.chat_id, text, buttons=rows)
            return True
        if len(parts) != 3:
            raise ValueError('Описание не найдено.')
        offset = int(parts[2])
        if offset < 0:
            raise ValueError('Описание не найдено.')
        first = db.query(Message).filter(Message.ticket_id == ticket.id,
            Message.direction == MessageDirection.INBOUND).order_by(Message.created_at, Message.id).first()
        body = first.body if first and first.body.strip() else 'Описание отдельно не добавлено. Полная тема заявки приведена выше.'
        last_page = max(0, (len(body) - 1) // DESCRIPTION_PAGE_SIZE) * DESCRIPTION_PAGE_SIZE
        offset = min(offset // DESCRIPTION_PAGE_SIZE * DESCRIPTION_PAGE_SIZE, last_page)
        _select(db, channel, state, contact, ticket, config, module)
        text = f'{ticket.display_number} — {ticket.subject}\n\nОписание заявки:\n{body[offset:offset + DESCRIPTION_PAGE_SIZE]}'
        rows, nav = [], []
        if offset:
            nav.append({'type': 'callback', 'text': '← Начало / назад', 'payload': f'ticketbody:{ticket.id}:{max(0, offset - DESCRIPTION_PAGE_SIZE)}'})
        if offset + DESCRIPTION_PAGE_SIZE < len(body):
            nav.append({'type': 'callback', 'text': 'Продолжение →', 'payload': f'ticketbody:{ticket.id}:{offset + DESCRIPTION_PAGE_SIZE}'})
        if nav:
            rows.append(nav)
        text += f'\n\nЧасть {offset // DESCRIPTION_PAGE_SIZE + 1} из {(len(body) - 1) // DESCRIPTION_PAGE_SIZE + 1}.'
        rows.append([{'type': 'callback', 'text': 'К карточке заявки и статусу', 'payload': f'ticket:{ticket.id}'}])
        from app.services.messenger_dialog import buttons
        module._send(config, parsed.chat_id, text, buttons=buttons(ticket, rows))
    except (ValueError, IndexError) as exc:
        module._send(config, parsed.chat_id, str(exc) if isinstance(exc, ValueError) else 'Заявка не найдена.')
    return True
