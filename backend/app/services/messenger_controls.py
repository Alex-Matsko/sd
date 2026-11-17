"""Safe navigation and customer feedback shared by both bots."""
from datetime import datetime, timezone

from app.core.enums import TicketStatus
from app.models.ticket import Ticket
from app.services import messenger_tickets

HELP_TEXT = (
    'Как пользоваться поддержкой\n\n'
    '1. «Создать новую» — опишите проблему, добавьте скриншоты или файлы.\n'
    '2. «Мои заявки» — активные, ожидающие приёмки и завершённые обращения.\n'
    '3. Чтобы уточнить вопрос по существующей заявке, нажмите «Ответить по этой заявке» или ответьте цитатой на сообщение бота.\n'
    '4. «Посмотреть результат» повторно пришлёт описание и файлы. После проверки нажмите «Принять результат» или «Нужна доработка».\n\n'
    '/cancel — отменить текущий ввод. Сама заявка не закрывается.\n'
    '/help — эта памятка.'
)


def cancel_buttons():
    return [[{'type': 'callback', 'text': 'Отменить ввод', 'payload': 'cmd:cancel'}]]


def _send(config, state, module, text, buttons=None):
    messenger_tickets.send_navigation(config, state.chat_id, module, text, buttons or module._main_menu_buttons())


def send_prompt(config, state, module, text='Опишите проблему, добавьте скриншоты или файлы — я создам заявку.'):
    _send(config, state, module, text, cancel_buttons())


def cancel_input(db, channel, config, state, contact, module):
    from app.services import messenger_dialog
    module._cancel_pending_ticket_flow(state)
    db.add(state); db.commit()
    text = 'Ввод отменён. Заявки и их статусы не изменены. Выберите обращение в «Мои заявки» или создайте новое.'
    if messenger_dialog.waiting(db, channel, config, state):
        text += '\nРанее присланные сообщения и файлы сохранены. Выберите заявку, чтобы прикрепить их.'
    else:
        active = db.get(Ticket, state.active_ticket_id) if state.active_ticket_id else None
        if active and active.contact_id == contact.id and active.status in messenger_dialog.REPLYABLE:
            text += f'\nТекущая переписка: {active.display_number} — {active.subject}. Обычное сообщение продолжит эту заявку.'
    _send(config, state, module, text)


def handle_text(db, channel, config, state, contact, parsed, module):
    if parsed.attachments:
        return False
    command = parsed.text.strip().lower()
    if command in ('/cancel', 'отменить ввод'):
        cancel_input(db, channel, config, state, contact, module)
        return True
    if command in ('/help', 'помощь'):
        _send(config, state, module, HELP_TEXT, module._main_menu_buttons() + cancel_buttons())
        return True
    return False


def handle_callback(db, channel, config, state, contact, parsed, module):
    payload = parsed.callback_payload or ''
    if payload == 'cmd:cancel':
        cancel_input(db, channel, config, state, contact, module)
        return True
    if payload == 'cmd:help':
        _send(config, state, module, HELP_TEXT, module._main_menu_buttons() + cancel_buttons())
        return True
    if not payload.startswith('csat:'):
        return False
    try:
        parts = payload.split(':')
        if len(parts) != 3:
            raise ValueError('Некорректная кнопка оценки. Откройте актуальную заявку в «Мои заявки».')
        try:
            ticket_id, rating = int(parts[1]), int(parts[2])
        except ValueError:
            raise ValueError('Некорректная кнопка оценки. Откройте актуальную заявку в «Мои заявки».') from None
        if rating not in range(1, 6):
            raise ValueError('Оценка должна быть от 1 до 5.')
        ticket = db.query(Ticket).filter_by(id=ticket_id, contact_id=contact.id).populate_existing().with_for_update().first()
        if ticket is None:
            raise ValueError('Заявка не найдена.')
        if ticket.status != TicketStatus.CLOSED:
            raise ValueError(f'{ticket.display_number}: оценить можно после закрытия заявки. Сначала проверьте и примите результат.')
        if ticket.csat_rating is not None:
            text = f'{ticket.display_number}: ваша оценка {ticket.csat_rating}/5 уже получена. Спасибо!'
        else:
            ticket.csat_rating, ticket.csat_rated_at = rating, datetime.now(timezone.utc)
            db.add(ticket); db.commit()
            text = f'{ticket.display_number}: спасибо за оценку {rating}/5!'
        _send(config, state, module, text)
    except (ValueError, IndexError) as exc:
        _send(config, state, module, str(exc) if isinstance(exc, ValueError) else 'Некорректная кнопка оценки.')
    return True
