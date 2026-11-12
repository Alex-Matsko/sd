"""Staff bell, realtime push and matching Telegram/MAX subscriptions."""

import logging

from sqlalchemy.orm import Session

from app.core.enums import NotificationType
from app.models.notification import Notification
from app.models.ticket import Ticket
from app.models.user import User

logger = logging.getLogger("app.notifications")


def notify(db: Session, user_ids: set[int], type_: NotificationType, ticket: Ticket, title: str, *, telegram=True) -> None:
    from app.services import realtime

    for user_id in user_ids:
        db.add(Notification(user_id=user_id, ticket_id=ticket.id, type=type_, title=title))
        # Срабатывает на коммите (семантика pg_notify), поэтому клиента
        # никогда не будят ради строки, которую откатил бы rollback.
        realtime.publish_notification(db, user_id, type_.value, title, ticket.id)
    if telegram:
        heading = {NotificationType.TICKET_ASSIGNED: "Назначен исполнитель",
                   NotificationType.CUSTOMER_REPLIED: "Ответ клиента"}.get(type_, title)
        notify_telegram(db, user_ids, heading, ticket)


def telegram_allowed(db, user, ticket):
    from app.services import ticket_access
    return bool(user.is_active and user.telegram_id and user.telegram_notification_scope != "off" and
                ticket_access.can_see(db, user, ticket) and
                ((user.telegram_notification_scope == "all" and ticket_access.sees_full_queue(user)) or
                 ticket.assigned_engineer_id == user.id))


def max_allowed(db, user, ticket):
    from app.services import ticket_access
    return bool(user.is_active and user.max_id and user.max_chat_id and user.max_notify_new_tickets and
                user.max_notification_scope in ("all", "assigned") and ticket_access.can_see(db, user, ticket) and
                ((user.max_notification_scope == "all" and ticket_access.sees_full_queue(user)) or
                 ticket.assigned_engineer_id == user.id))


def notify_telegram(db: Session, user_ids: set[int], title: str, ticket: Ticket, *, broadcast_all: bool = True) -> None:
    # Compatibility entrypoint: both messengers use the same card and scope.
    from app.services import max_channel, telegram_channel
    from app.services.channel_queue import enqueue_notification
    from app.services.ticket_messages import ticket_notice
    enabled = {"telegram": telegram_channel.load_telegram_config(db) is not None,
               "max": max_channel.load_max_config(db) is not None}
    if not any(enabled.values()):
        return
    users = db.query(User).filter(User.is_active.is_(True)).all()
    text = ticket_notice(ticket, title)
    for user in users:
        if not broadcast_all and user.id not in user_ids:
            continue
        for channel, recipient, allowed in (("telegram", user.telegram_id, telegram_allowed(db, user, ticket)),
                                             ("max", user.max_chat_id, max_allowed(db, user, ticket))):
            if not enabled[channel] or not allowed:
                continue
            job = enqueue_notification(db, channel, recipient, text)
            job.ticket_id = ticket.id
            job.payload = {**job.payload, "staff_user_id": user.id, "staff_notice": "ticket_event"}
            if channel == "max":
                job.payload = {**job.payload, "staff_max_id": user.max_id}


def notify_status_change(db: Session, ticket: Ticket, status) -> None:
    from app.services.ticket_messages import status_headline
    notify_telegram(db, set(), status_headline(status), ticket)


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
    """Bell to the assignee; bot events also reach full-queue subscribers."""
    notify(
        db,
        {ticket.assigned_engineer_id} if ticket.assigned_engineer_id else set(),
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
    notify_new_ticket_messengers(db, ticket, actor)
    if not recipients:
        return

    type_ = NotificationType.TICKET_ASSIGNED if (ticket.assigned_engineer_id or ticket.team_id) else NotificationType.TICKET_UNASSIGNED
    notify(db, recipients, type_, ticket, title, telegram=False)


def notify_new_ticket_messengers(db: Session, ticket: Ticket, actor: User | None = None) -> None:
    from sqlalchemy.dialects.postgresql import insert
    from app.models.channel_job import ChannelJob
    from sqlalchemy import or_
    from app.services import max_channel, telegram_channel, ticket_access
    from app.services.ticket_messages import ticket_notice
    enabled = {"max": max_channel.load_max_config(db) is not None, "telegram": telegram_channel.load_telegram_config(db) is not None}
    if not any(enabled.values()):
        return
    text = ticket_notice(ticket, "Новая заявка")
    users = db.query(User).filter(User.is_active.is_(True), or_(User.max_id.isnot(None), User.telegram_id.isnot(None))).all()
    for user in users:
        if (actor and actor.id == user.id) or not ticket_access.can_see(db, user, ticket):
            continue
        for channel, recipient, allowed in (("max", user.max_chat_id, max_allowed(db, user, ticket)),
                                            ("telegram", user.telegram_id, telegram_allowed(db, user, ticket))):
            if not enabled[channel] or not allowed:
                continue
            payload = {"recipient": recipient, "text": text, "_sd_summary": f"Новая заявка {ticket.display_number}",
                       "staff_user_id": user.id, "staff_notice": "new_ticket"}
            if channel == "max":
                payload["staff_max_id"] = user.max_id
            db.execute(insert(ChannelJob).values(kind="outbound", channel=channel, state="pending", attempts=0,
                       event_key=f"staff:{channel}:new-ticket:{ticket.id}:user:{user.id}", stream_key=f"{channel}:chat:{recipient}",
                       ticket_id=ticket.id, payload=payload).on_conflict_do_nothing(index_elements=[ChannelJob.event_key]))
