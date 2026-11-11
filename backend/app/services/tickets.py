from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.enums import ImpactUrgencyLevel, SLA_PAUSING_STATUSES, TicketStatus
from app.models.asset import Asset
from app.models.category import Category
from app.models.team import Team
from app.models.contact import Contact
from app.models.organization import Organization
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ticket import TicketClientChange, TicketCreate, TicketUpdate
from app.services import audit, staff_notifications, priority as priority_service, routing, sla
from app.services.contracts import resolve_contract_and_tariff

# Allowed status transitions (section 4.2). CLOSED and CANCELLED are terminal.
ALLOWED_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.NEW: {TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED},
    # NEW добавлен ради снятия исполнителя: заявка без исполнителя со
    # статусом «Назначена» — противоречие, она снова в общей очереди.
    TicketStatus.ASSIGNED: {TicketStatus.NEW, TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED},
    TicketStatus.IN_PROGRESS: {
        TicketStatus.WAITING_CUSTOMER,
        TicketStatus.WAITING_THIRD_PARTY,
        TicketStatus.RESOLVED,
        TicketStatus.CANCELLED,
    },
    TicketStatus.WAITING_CUSTOMER: {TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED},
    TicketStatus.WAITING_THIRD_PARTY: {TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED},
    TicketStatus.RESOLVED: {TicketStatus.CLOSED, TicketStatus.IN_PROGRESS},
    TicketStatus.CLOSED: set(),
    TicketStatus.CANCELLED: set(),
}


def _validate_references(db: Session, organization_id: int, asset_id: int | None, category_id: int | None) -> None:
    if asset_id is not None:
        asset = db.get(Asset, asset_id)
        if asset is None or asset.organization_id != organization_id:
            raise ValueError("Актив не найден в выбранной организации")
    if category_id is not None and db.get(Category, category_id) is None:
        raise ValueError("Категория не найдена")


def create_ticket(db: Session, payload: TicketCreate, actor: User | None) -> Ticket:
    contact = db.get(Contact, payload.contact_id)
    if contact is None:
        raise ValueError("Контакт не найден")

    _validate_references(db, contact.organization_id, payload.asset_id, payload.category_id)
    contract, tariff, has_no_active_contract = resolve_contract_and_tariff(db, contact.organization_id)

    if payload.manual_priority is not None:
        ticket_priority = payload.manual_priority
    else:
        ticket_priority = priority_service.compute_priority(db, payload.impact, payload.urgency)

    # Признаки заявки передаются целиком: правила могут смотреть на канал,
    # приоритет и тип, а не только на организацию и категорию.
    team_id, engineer_id = routing.resolve_assignment(
        db,
        contact.organization_id,
        payload.category_id,
        channel=payload.channel.value if payload.channel else None,
        priority=ticket_priority.value,
        ticket_type=payload.type.value if payload.type else None,
        asset_id=payload.asset_id,
    )
    status = TicketStatus.ASSIGNED if (team_id or engineer_id) else TicketStatus.NEW

    ticket = Ticket(
        type=payload.type,
        channel=payload.channel,
        subject=payload.subject,
        organization_id=contact.organization_id,
        contact_id=contact.id,
        contract_id=contract.id if contract else None,
        tariff_id=tariff.id,
        has_no_active_contract=has_no_active_contract,
        asset_id=payload.asset_id,
        category_id=payload.category_id,
        impact=payload.impact,
        urgency=payload.urgency,
        priority=ticket_priority,
        priority_override_reason=payload.manual_priority_reason,
        status=status,
        assigned_engineer_id=engineer_id,
        team_id=team_id,
        parent_ticket_id=payload.parent_ticket_id,
    )
    db.add(ticket)
    db.flush()
    sla.set_initial_deadlines(db, ticket)

    if payload.initial_message:
        from app.core.enums import MessageDirection
        from app.schemas.message import MessageCreate
        from app.services import messages as messages_service

        messages_service.add_message(
            db,
            ticket,
            MessageCreate(direction=MessageDirection.INBOUND, body=payload.initial_message, channel=payload.channel),
            author_contact=contact,
        )

    audit.record(
        db,
        entity_type="ticket",
        entity_id=ticket.id,
        action="created",
        user_id=actor.id if actor else None,
        changes={"status": status.value, "priority": ticket_priority.value},
    )
    db.commit()
    db.refresh(ticket)

    # После commit: уведомление ссылается на display_number, а он строится из
    # присвоенного базой номера. И адресат не должен узнать о заявке раньше,
    # чем она станет видимой другим сессиям.
    staff_notifications.notify_new_ticket(db, ticket, actor)
    # Собственный commit: pg_notify срабатывает только на коммите, иначе живой
    # push не ушёл бы, а записи в колокольчике повисли бы до следующей записи
    # в этой сессии.
    db.commit()
    return ticket


def transition_status(db: Session, ticket: Ticket, new_status: TicketStatus, actor: User | None) -> Ticket:
    old_status = TicketStatus(ticket.status)
    allowed = ALLOWED_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise ValueError(f"Переход {old_status.value} -> {new_status.value} не разрешён")

    now = datetime.now(timezone.utc)

    was_paused = old_status in SLA_PAUSING_STATUSES
    will_be_paused = new_status in SLA_PAUSING_STATUSES
    if not was_paused and will_be_paused:
        ticket.sla_paused_at = now
    elif was_paused and not will_be_paused and ticket.sla_paused_at is not None:
        elapsed_minutes = int((now - ticket.sla_paused_at).total_seconds() // 60)
        ticket.sla_paused_minutes_total = (ticket.sla_paused_minutes_total or 0) + elapsed_minutes
        sla.apply_resume(db, ticket, now)
        ticket.sla_paused_at = None

    # Переоткрытие: «решено» и «решено так, что не вернулось» — разные вещи,
    # и доля возвратов в ITIL считается показателем качества решения. Раньше
    # переоткрытие не оставляло следа вообще.
    if old_status == TicketStatus.RESOLVED and new_status == TicketStatus.IN_PROGRESS:
        ticket.reopen_count = (ticket.reopen_count or 0) + 1

    # First resolution is fixed permanently - reopening never overwrites it
    # (docs/decisions.md: "SLA при переоткрытии заявки клиентом").
    if new_status == TicketStatus.RESOLVED and ticket.resolved_at is None:
        ticket.resolved_at = now
        sla.register_resolution(ticket, now)
    if new_status == TicketStatus.CLOSED:
        ticket.closed_at = now

    ticket.status = new_status
    db.add(ticket)

    # Messenger notifications (section 2.1/2.2) - each channel module no-ops
    # for tickets on a different channel (see request_csat's own docstring),
    # so calling both unconditionally is safe. Deferred imports: both channel
    # modules import tickets_service.create_ticket.
    from app.services import max_channel, telegram_channel

    if new_status == TicketStatus.CLOSED:
        max_channel.request_csat(db, ticket)
        telegram_channel.request_csat(db, ticket)
    max_channel.notify_status_change(db, ticket, new_status)
    telegram_channel.notify_status_change(db, ticket, new_status)

    audit.record(
        db,
        entity_type="ticket",
        entity_id=ticket.id,
        action="status_changed",
        user_id=actor.id if actor else None,
        changes={"from": old_status.value, "to": new_status.value},
    )
    db.commit()
    db.refresh(ticket)
    return ticket


def _follow_assignment(db: Session, ticket: Ticket, actor: User | None) -> None:
    """Подтягивает статус за назначением.

    Только между «Новой» и «Назначена»: заявка в работе или ожидании от
    смены исполнителя статус менять не должна — там уже идёт работа, и
    откат назад стёр бы её ход.
    """
    status = TicketStatus(ticket.status)
    has_assignee = bool(ticket.assigned_engineer_id or ticket.team_id)

    if status == TicketStatus.NEW and has_assignee:
        transition_status(db, ticket, TicketStatus.ASSIGNED, actor)
    elif status == TicketStatus.ASSIGNED and not has_assignee:
        transition_status(db, ticket, TicketStatus.NEW, actor)


def update_ticket(db: Session, ticket: Ticket, payload: TicketUpdate, actor: User | None) -> Ticket:
    provided = payload.model_fields_set
    _validate_references(
        db, ticket.organization_id,
        payload.asset_id if "asset_id" in provided else ticket.asset_id,
        payload.category_id if "category_id" in provided else ticket.category_id,
    )
    if payload.assigned_engineer_id is not None:
        engineer = db.get(User, payload.assigned_engineer_id)
        if engineer is None or not engineer.is_active:
            raise ValueError("Исполнитель не найден или неактивен")
    if payload.team_id is not None and db.get(Team, payload.team_id) is None:
        raise ValueError("Команда не найдена")
    if payload.manual_priority is not None and not (payload.manual_priority_reason or "").strip():
        raise ValueError("При ручном приоритете нужно указать manual_priority_reason")
    if payload.status is not None and TicketStatus(payload.status) != TicketStatus(ticket.status):
        transition_status(db, ticket, TicketStatus(payload.status), actor)

    changed: dict = {}
    # "Field was sent as null" (clear it) vs "field wasn't sent at all" (leave
    # it) - `is not None` alone can't tell those apart, which silently swallowed
    # the UI's "Не назначено"/"Без команды" selections: the dropdown sent null,
    # the request succeeded, and the assignee stayed put (found in audit).
    provided = payload.model_fields_set

    if "assigned_engineer_id" in provided and payload.assigned_engineer_id != ticket.assigned_engineer_id:
        changed["assigned_engineer_id"] = {"from": ticket.assigned_engineer_id, "to": payload.assigned_engineer_id}
        ticket.assigned_engineer_id = payload.assigned_engineer_id

        from app.services import email_channel, max_channel, telegram_channel

        # Clearing the assignee notifies nobody - the channel helpers no-op
        # on a None engineer, so unassigning stays silent for the client.
        # Каждый помощник сам проверяет канал заявки, поэтому вызываются все:
        # клиент узнаёт об исполнителе там, откуда написал. Почта была
        # пропущена — писавший письмом не знал, к кому обращаться.
        assigned_engineer = db.get(User, payload.assigned_engineer_id) if payload.assigned_engineer_id else None
        max_channel.notify_assignment_change(db, ticket, assigned_engineer)
        telegram_channel.notify_assignment_change(db, ticket, assigned_engineer)
        email_channel.notify_assignment_change(db, ticket, assigned_engineer)
        # Клиент о назначении узнавал, а сам исполнитель — нет (ТЗ р. 8).
        staff_notifications.notify_assignment(db, ticket, assigned_engineer)

    if "team_id" in provided and payload.team_id != ticket.team_id:
        changed["team_id"] = {"from": ticket.team_id, "to": payload.team_id}
        ticket.team_id = payload.team_id

    # Статус следует за назначением сам. Раньше диспетчер назначал инженера,
    # а заявка оставалась «Новой», и очередь новых заявок наполнялась уже
    # разобранными — их приходилось переводить вторым действием, о котором
    # легко забыть. Тот же расклад маршрутизация делает при создании заявки
    # (create_ticket), так что поведение теперь одинаковое.
    if "assigned_engineer_id" in provided or "team_id" in provided:
        _follow_assignment(db, ticket, actor)

    if "is_recurring_problem" in provided and payload.is_recurring_problem != ticket.is_recurring_problem:
        # Метка попадает в историю заявки: это решение о том, что случай не
        # разовый, и по нему потом ищут связанные обращения.
        changed["is_recurring_problem"] = {
            "from": ticket.is_recurring_problem,
            "to": payload.is_recurring_problem,
        }
        ticket.is_recurring_problem = bool(payload.is_recurring_problem)

    for field in ("planned_due_at", "estimated_minutes"):
        if field in provided and getattr(payload, field) != getattr(ticket, field):
            before, after = getattr(ticket, field), getattr(payload, field)
            changed[field] = {"from": before.isoformat() if isinstance(before, datetime) else before,
                              "to": after.isoformat() if isinstance(after, datetime) else after}
            setattr(ticket, field, after)

    if "category_id" in provided:
        ticket.category_id = payload.category_id
    if "asset_id" in provided:
        ticket.asset_id = payload.asset_id
    if payload.impact is not None:
        ticket.impact = payload.impact
    if payload.urgency is not None:
        ticket.urgency = payload.urgency

    if payload.manual_priority is not None:
        if not payload.manual_priority_reason:
            raise ValueError("При ручном приоритете нужно указать manual_priority_reason")
        changed["priority"] = {
            "from": ticket.priority,
            "to": payload.manual_priority.value,
            "reason": payload.manual_priority_reason,
        }
        ticket.priority = payload.manual_priority
        ticket.priority_override_reason = payload.manual_priority_reason
    elif payload.impact is not None and payload.urgency is not None:
        new_priority = priority_service.compute_priority(
            db, ImpactUrgencyLevel(ticket.impact), ImpactUrgencyLevel(ticket.urgency)
        )
        if new_priority != ticket.priority:
            changed["priority"] = {"from": ticket.priority, "to": new_priority.value}
            ticket.priority = new_priority
            ticket.priority_override_reason = None

    if "priority" in changed:
        sla.recompute_after_priority_change(db, ticket)

    if changed:
        audit.record(
            db,
            entity_type="ticket",
            entity_id=ticket.id,
            action="updated",
            user_id=actor.id if actor else None,
            changes=changed,
        )

    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def change_client(db: Session, ticket: Ticket, payload: TicketClientChange, actor: User | None) -> Ticket:
    """Привязка заявки к организации и контакту — прежде всего пришедших из
    бота: незнакомый отправитель попадает в «Неизвестные» (unknown_queue).

    Контакт заявки не подменяется: ответы инженера уходят в Telegram и MAX
    по контакту, и чужой контакт оборвал бы переписку. Поэтому либо тот же
    человек переносится в организацию, либо его контакт объединяется с уже
    заведённым контактом организации — с привязками бота и всей историей.
    Объединять можно только контакт из «Неизвестных»: два заведённых
    контакта — это, скорее всего, два разных человека.

    Вместе с заявкой переезжают все заявки этого человека, оставшиеся в
    прежней организации: из бота он обычно успевает написать не одну.
    Договор, тариф и сроки SLA пересчитываются по новой организации."""
    from app.services import messenger_common
    from app.services.unknown_queue import UNKNOWN_ORGANIZATION_NAME

    organization = db.get(Organization, payload.organization_id)
    if organization is None:
        raise ValueError("Организация не найдена")
    current = db.get(Contact, ticket.contact_id)
    old_org_id = ticket.organization_id
    old_contact_id = current.id

    person = current
    if payload.contact_id is not None and payload.contact_id != current.id:
        target = db.get(Contact, payload.contact_id)
        if target is None or target.organization_id != organization.id:
            raise ValueError("Контакт не из выбранной организации")
        current_org = db.get(Organization, current.organization_id)
        if current_org is None or current_org.name != UNKNOWN_ORGANIZATION_NAME:
            raise ValueError(
                f"Контакт «{current.full_name}» уже заведён в организации — объединять можно только контакты из «Неизвестных»"
            )
        moved_ids = [
            t.id for t in db.query(Ticket).filter(Ticket.contact_id == current.id, Ticket.organization_id == old_org_id)
        ]
        messenger_common.merge_contacts(db, from_contact=current, into_contact=target)
        person = target
    else:
        if old_org_id == organization.id and current.organization_id == organization.id:
            return ticket
        moved_ids = [
            t.id for t in db.query(Ticket).filter(Ticket.contact_id == current.id, Ticket.organization_id == old_org_id)
        ]
        current.organization_id = organization.id
        db.add(current)

    contract, tariff, has_no_active_contract = resolve_contract_and_tariff(db, organization.id)
    for moved in db.query(Ticket).filter(Ticket.id.in_(moved_ids)).all():
        changes: dict = {"organization_id": {"from": moved.organization_id, "to": organization.id}}
        if old_contact_id != person.id:
            changes["contact_id"] = {"from": old_contact_id, "to": person.id}
        moved.organization_id = organization.id
        moved.contact_id = person.id
        if moved.asset_id is not None:
            asset = db.get(Asset, moved.asset_id)
            if asset is None or asset.organization_id != organization.id:
                changes["asset_id"] = {"from": moved.asset_id, "to": None}
                moved.asset_id = None
        moved.contract_id = contract.id if contract else None
        moved.tariff_id = tariff.id
        moved.has_no_active_contract = has_no_active_contract
        sla.recompute_after_priority_change(db, moved)
        audit.record(
            db,
            entity_type="ticket",
            entity_id=moved.id,
            action="client_changed",
            user_id=actor.id if actor else None,
            changes=changes,
        )
        db.add(moved)

    db.commit()
    db.refresh(ticket)
    return ticket
