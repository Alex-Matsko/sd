"""One plain-text ticket card for Telegram and MAX, with audience-safe links."""
from urllib.parse import urlsplit

from app.config import settings
from app.core.enums import TicketStatus

STATUS_LABELS_RU = {
    TicketStatus.NEW: "Новая", TicketStatus.ASSIGNED: "Назначена",
    TicketStatus.IN_PROGRESS: "В работе", TicketStatus.WAITING_CUSTOMER: "Ждём клиента",
    TicketStatus.WAITING_THIRD_PARTY: "Ждём третью сторону", TicketStatus.RESOLVED: "Решена",
    TicketStatus.CLOSED: "Закрыта", TicketStatus.CANCELLED: "Отменена",
}


def ticket_url(ticket, *, client=False):
    base = (settings.portal_base_url if client else settings.staff_base_url).strip().rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return ''
    return f'{base}?ticket={ticket.id}' if client else f'{base}/tickets/{ticket.id}'


def status_headline(status):
    return {TicketStatus.RESOLVED: 'Работы завершены', TicketStatus.CLOSED: 'Заявка закрыта',
            TicketStatus.CANCELLED: 'Заявка отменена'}.get(status, 'Статус заявки изменён')


def ticket_notice(ticket, headline, *, client=False, detail=None):
    status = TicketStatus(ticket.status)
    lines = [headline, f'Заявка: {ticket.display_number}', f'Тема: {ticket.subject}',
             f'Статус: {STATUS_LABELS_RU[status]}', f'Приоритет: {ticket.priority.value}']
    if not client:
        lines.append(f'Клиент: {ticket.organization.name}')
        lines.append(f'Канал: {ticket.channel.value.upper()}')
    from sqlalchemy.orm import object_session
    from app.models.user import User
    session = object_session(ticket)
    engineer = session.get(User, ticket.assigned_engineer_id) if session and ticket.assigned_engineer_id else None
    lines.append(f'Исполнитель: {engineer.full_name if engineer else "Не назначен"}')
    if detail:
        lines.extend(['', detail])
    url = ticket_url(ticket, client=client)
    if url:
        lines.extend(['', f'Открыть заявку: {url}'])
    return '\n'.join(lines)
