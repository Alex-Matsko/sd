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
            from app.services.channel_queue import enqueue_notification
            enqueue_notification(db, "telegram", user.telegram_id, title)
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


# Приоритеты, которые в колокольчике должны отличаться от рядового обращения.
_URGENT_PRIORITIES = {"P1", "P2"}


def _headline(ticket: Ticket, prefix: str) -> str:
    """Авария не должна выглядеть в списке как обычная заявка: у P1/P2
    приоритет выносится в начало строки, а не теряется в карточке."""
    priority = str(getattr(ticket.priority, "value", ticket.priority))
    mark = f"[{priority}] " if priority in _URGENT_PRIORITIES else ""
    return f"{mark}{prefix} {ticket.display_number}: {ticket.subject}"


def _team_recipients(db: Session, team_id: int) -> set[int]:
    """Вся команда, а не только руководитель.

    ТЗ 4.4 допускает самоназначение инженером внутри группы — значит, о
    появившейся работе должны узнать те, кто её возьмёт. Уведомлять одного
    руководителя означало бы, что распределение всегда идёт через него.
    """
    from app.models.team import Team
    from app.models.user import TeamMembership

    recipients = {row[0] for row in db.query(TeamMembership.user_id).filter(TeamMembership.team_id == team_id)}
    team = db.get(Team, team_id)
    if team is not None and team.lead_user_id:
        recipients.add(team.lead_user_id)
    return recipients


def _dispatchers(db: Session) -> set[int]:
    """Кому показывать нераспределённые заявки.

    По ТЗ р. 6 общую очередь ведёт диспетчер. Если диспетчера в системе нет
    (у небольшой компании роли часто совмещены), уведомление уходит
    руководителям — иначе заявка не досталась бы никому, а это ровно тот
    случай, ради которого уведомление и вводится.
    """
    from app.core.enums import UserRole
    from app.models.user import User as UserModel

    def by_role(role: UserRole) -> set[int]:
        return {
            row[0]
            for row in db.query(UserModel.id).filter(UserModel.role == role, UserModel.is_active.is_(True))
        }

    return by_role(UserRole.DISPATCHER) or by_role(UserRole.MANAGER) or by_role(UserRole.ADMIN)


def notify_new_ticket(db: Session, ticket: Ticket, actor: User | None = None) -> None:
    """Уведомление о только что созданной заявке.

    Маршрутизация назначает исполнителя прямо при создании, но уведомление
    об этом раньше отправлялось только при ручной смене исполнителя в
    карточке. В результате первым сигналом о заявке становилось
    предупреждение о 75% SLA — то есть инженер узнавал о работе, когда срок
    уже горел.
    """
    if ticket.assigned_engineer_id:
        recipients = {ticket.assigned_engineer_id}
        title = _headline(ticket, "Новая заявка на вас —")
    elif ticket.team_id:
        recipients = _team_recipients(db, ticket.team_id)
        title = _headline(ticket, "Новая заявка на вашу группу —")
    else:
        recipients = _dispatchers(db)
        title = _headline(ticket, "Новая заявка без исполнителя —")

    # Тот, кто сам завёл заявку, уведомления о ней не получает: это шум.
    if actor is not None:
        recipients = recipients - {actor.id}
    if not recipients:
        return

    type_ = NotificationType.TICKET_ASSIGNED if (ticket.assigned_engineer_id or ticket.team_id) else NotificationType.TICKET_UNASSIGNED
    notify(db, recipients, type_, ticket, title)
