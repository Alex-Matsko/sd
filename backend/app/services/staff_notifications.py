"""Уведомления сотруднику: в интерфейсе и в Telegram (ТЗ р. 8).

Доставка была написана внутри SLA-движка и оттуда никому не доступна,
поэтому уведомлений в системе существовало ровно четыре вида — все про SLA.
При этом ТЗ 4.2 прямо требует: «Ответ клиента… автоматически возвращает её
"В работе" **и уведомляет исполнителя"». Статус переключался, уведомления не
было; о назначенной заявке инженер тоже не узнавал — о нём узнавал клиент в
мессенджере, а исполнитель нет.

Здесь общий канал доставки: запись в колокольчик, живой push через
LISTEN/NOTIFY и дубль в Telegram тем, кто привязал аккаунт.
"""

import logging

from sqlalchemy.orm import Session

from app.core.enums import NotificationType
from app.models.notification import Notification
from app.models.ticket import Ticket
from app.models.user import User

logger = logging.getLogger("app.notifications")


def notify(db: Session, user_ids: set[int], type_: NotificationType, ticket: Ticket, title: str) -> None:
    from app.services import realtime

    for user_id in user_ids:
        db.add(Notification(user_id=user_id, ticket_id=ticket.id, type=type_, title=title))
        # Срабатывает на коммите (семантика pg_notify), поэтому клиента
        # никогда не будят ради строки, которую откатил бы rollback.
        realtime.publish_notification(db, user_id, type_.value, title, ticket.id)
    notify_telegram(db, user_ids, title)


def notify_telegram(db: Session, user_ids: set[int], title: str) -> None:
    """Дубль в Telegram (ТЗ р. 8). Ничего не делает для тех, кто не привязал
    аккаунт (Профиль → код, `/link`), и если канал вообще не настроен.
    Отложенный импорт: telegram_channel → messenger_common → tickets_service
    замкнулся бы на этот модуль."""
    if not user_ids:
        return
    from app.services import telegram_channel, telegram_client

    config = telegram_channel.load_telegram_config(db)
    if config is None:
        return
    recipients = db.query(User).filter(User.id.in_(user_ids), User.telegram_id.isnot(None)).all()
    for user in recipients:
        try:
            telegram_client.send_message(config.base_url, config.token, user.telegram_id, title)
        except Exception:
            # Недоступный Telegram не должен ронять операцию, ради которой
            # уведомление отправлялось: запись в колокольчике уже создана.
            logger.exception("Не удалось отправить уведомление в Telegram пользователю %s", user.id)


def notify_assignment(db: Session, ticket: Ticket, engineer: User | None) -> None:
    """Инженеру — о заявке, которая теперь на нём."""
    if engineer is None:
        return
    notify(
        db,
        {engineer.id},
        NotificationType.TICKET_ASSIGNED,
        ticket,
        f"На вас назначена заявка {ticket.display_number}: {ticket.subject}",
    )


def notify_customer_reply(db: Session, ticket: Ticket) -> None:
    """Исполнителю — об ответе клиента (ТЗ 4.2).

    Некому уведомлять — заявка ещё не назначена: её и так видно в общей
    очереди, а рассылать всем подряд означало бы сделать колокольчик
    бесполезным.
    """
    if not ticket.assigned_engineer_id:
        return
    notify(
        db,
        {ticket.assigned_engineer_id},
        NotificationType.CUSTOMER_REPLIED,
        ticket,
        f"Клиент ответил в заявке {ticket.display_number}: {ticket.subject}",
    )
