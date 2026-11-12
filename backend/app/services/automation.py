"""Time rules: eligibility, read-only preview and atomic actions plus outbox."""
from datetime import datetime, timedelta, timezone
import hashlib
import re

from sqlalchemy.orm import Session

from app.core.enums import AutomationTriggerType, Channel, MessageDirection, UserRole
from app.models.audit import AuditLog
from app.models.automation_rule import AutomationRule, AutomationRun
from app.models.channel_job import ChannelJob
from app.models.message import Message
from app.models.ticket import Ticket
from app.models.user import User
from app.services import tickets as tickets_service


def _status_anchor(db, ticket):
    last_change = db.query(AuditLog).filter_by(entity_type='ticket', entity_id=ticket.id, action='status_changed').order_by(
        AuditLog.created_at.desc(), AuditLog.id.desc()).first()
    return (last_change.created_at, last_change.id) if last_change is not None else (ticket.created_at, 0)


def _time_in_current_status(db, ticket):
    return _status_anchor(db, ticket)[0]


def _candidates(db, rule):
    query = db.query(Ticket).filter(Ticket.status == rule.from_status)
    filters = rule.filters or {}
    for name in ('organization_id', 'category_id', 'team_id', 'assigned_engineer_id'):
        if filters.get(name):
            query = query.filter(getattr(Ticket, name) == filters[name])
    if filters.get('unassigned'):
        query = query.filter(Ticket.assigned_engineer_id.is_(None))
    if filters.get('priorities'):
        query = query.filter(Ticket.priority.in_(filters['priorities']))
    if filters.get('channels'):
        query = query.filter(Ticket.channel.in_(filters['channels']))
    return query


def _episode(db, rule, ticket, now):
    since, anchor_id = _status_anchor(db, ticket)
    if rule.trigger_type == AutomationTriggerType.DEADLINE_OVERDUE:
        since = ticket.planned_due_at
        if since is None and ticket.sla_paused_at is None:
            since = ticket.sla_resolution_due_at
        if since is None:
            return None
    elif rule.trigger_type in (AutomationTriggerType.RESOLVED_WITHOUT_REPLY, AutomationTriggerType.STATUS_WITHOUT_REPLY):
        reply = db.query(Message).filter(Message.ticket_id == ticket.id,
            Message.direction == MessageDirection.INBOUND).order_by(Message.created_at.desc(), Message.id.desc()).first()
        if reply is not None and reply.created_at >= since:
            since = reply.created_at
            anchor_id = f'{anchor_id}:reply:{reply.id}'
    hours = rule.delay_hours if rule.delay_hours is not None else rule.threshold_days * 24
    if now < since + timedelta(hours=hours):
        return None
    return hashlib.sha256(f'{ticket.status.value}:{anchor_id}:{since.isoformat()}'.encode()).hexdigest()


def _actions(rule):
    return rule.actions or [{'type': 'change_status'}]


def _recipients(db, ticket, action):
    from app.services import staff_notifications, ticket_access
    target = action.get('recipient', 'assignee')
    if target == 'assignee':
        ids = {ticket.assigned_engineer_id} if ticket.assigned_engineer_id else set()
    elif target == 'team':
        ids = staff_notifications._team_recipients(db, ticket.team_id) if ticket.team_id else set()
    elif target == 'managers':
        ids = {row[0] for row in db.query(User.id).filter(User.role.in_([UserRole.ADMIN, UserRole.MANAGER]))}
    else:
        ids = set(action.get('user_ids', []))
    return {u.id for u in db.query(User).filter(User.id.in_(ids), User.is_active.is_(True)) if ticket_access.can_see(db, u, ticket)}


def _channel(ticket, action):
    return Channel(ticket.channel if action.get('channel', 'ticket') == 'ticket' else action['channel'])


def _preflight(db, rule, ticket):
    from app.services import email_channel, max_channel, telegram_channel
    from app.schemas.automation_rule import AutomationRuleCreate
    try:
        AutomationRuleCreate.model_validate(rule, from_attributes=True)
    except ValueError:
        return 'Проверьте параметры правила'
    for action in _actions(rule):
        if action['type'] == 'change_status' and rule.to_status not in tickets_service.ALLOWED_TRANSITIONS.get(ticket.status, set()):
            return 'Переход между статусами недопустим'
        if action['type'] == 'notify_staff' and not _recipients(db, ticket, action):
            return 'Нет активных получателей с доступом к заявке'
        if action['type'] == 'client_reminder':
            channel = _channel(ticket, action)
            if channel == Channel.PORTAL:
                # The portal lists every customer-visible message for this contact.
                continue
            if channel == Channel.EMAIL:
                if email_channel.load_email_config(db) is None:
                    return 'Почтовый канал отключён или не настроен'
                if not ticket.contact.emails:
                    return 'У клиента не указан email'
            elif channel in (Channel.MAX, Channel.TELEGRAM):
                module = max_channel if channel == Channel.MAX else telegram_channel
                config = module.load_max_config(db) if channel == Channel.MAX else module.load_telegram_config(db)
                if config is None:
                    return 'Канал напоминания отключён или не настроен'
                if module._find_chat_state(db, ticket.contact_id) is None:
                    return 'Не найден чат клиента для напоминания'
            else:
                return 'Укажите email, Telegram, MAX или личный кабинет для напоминания'
    return None


def render_template(text, ticket, *, client=False):
    from app.services.ticket_messages import ticket_url
    engineer = ticket.assigned_engineer
    due = ticket.planned_due_at or ticket.sla_resolution_due_at
    values = {'ticket_number': ticket.display_number, 'subject': ticket.subject, 'client_name': ticket.contact.full_name,
              'organization': ticket.organization.name, 'assignee': engineer.full_name if engineer else 'Не назначен',
              'due_at': due.strftime('%d.%m.%Y %H:%M UTC') if due else 'Не указан', 'ticket_url': ticket_url(ticket, client=client)}
    return re.sub(r'\{\{\s*(.*?)\s*\}\}', lambda match: values.get(match[1], ''), text)


def preview_rule(db, rule, now=None):
    now = now or datetime.now(timezone.utc)
    result = {'matched_count': 0, 'ready_count': 0, 'samples': []}
    for ticket in _candidates(db, rule).order_by(Ticket.id):
        if _episode(db, rule, ticket, now) is None:
            continue
        result['matched_count'] += 1
        error = _preflight(db, rule, ticket)
        if not error:
            result['ready_count'] += 1
        if len(result['samples']) < 20:
            result['samples'].append({'ticket_id': ticket.id, 'display_number': ticket.display_number, 'subject': ticket.subject,
                'error': error, 'actions': [{'type': a['type'], 'text': render_template(a.get('text', ''), ticket,
                    client=a['type'] == 'client_reminder'), 'recipient_count': len(_recipients(db, ticket, a)) if a['type'] == 'notify_staff' else None}
                    for a in _actions(rule)]})
    return result


def _next_run(db, rule, ticket, episode, now):
    previous = db.query(AutomationRun).filter_by(rule_id=rule.id, ticket_id=ticket.id, revision=rule.revision,
        episode=episode).order_by(AutomationRun.occurrence.desc()).first()
    if previous is None:
        return 1, None
    if previous.state == 'error':
        if previous.attempts >= 3 or (previous.available_at and now < previous.available_at):
            return None
        return previous.occurrence, previous
    if rule.repeat_hours is None or previous.occurrence >= rule.max_runs or now < previous.created_at + timedelta(hours=rule.repeat_hours):
        return None
    # A pending or failed outbound message is retried through the channel journal,
    # never replaced by another reminder while its delivery is unresolved.
    if previous.message_ids and db.query(ChannelJob.id).filter(ChannelJob.message_id.in_(previous.message_ids),
            ChannelJob.state.notin_(['sent', 'discarded'])).first():
        return None
    return previous.occurrence + 1, None


def _apply(db, rule, ticket, run):
    from app.schemas.message import MessageCreate
    from app.services import messages, staff_notifications
    from app.core.enums import NotificationType
    ids = []
    for index, action in enumerate(_actions(rule)):
        kind = action['type']
        text = render_template(action.get('text', ''), ticket, client=kind == 'client_reminder')
        if kind == 'change_status':
            tickets_service.transition_status(db, ticket, rule.to_status, actor=None)
        elif kind in ('client_reminder', 'internal_note'):
            message = messages.add_message(db, ticket, MessageCreate(body=text,
                direction=MessageDirection.OUTBOUND if kind == 'client_reminder' else MessageDirection.INTERNAL_NOTE,
                channel=_channel(ticket, action) if kind == 'client_reminder' else ticket.channel),
                automation_key=f'automation:{run.id}:{index}')
            ids.append(message.id)
        else:
            recipients = _recipients(db, ticket, action)
            staff_notifications.notify(db, recipients, NotificationType.AUTOMATION_REMINDER, ticket, text[:500], telegram=False)
            staff_notifications.notify_telegram(db, recipients, text, ticket, broadcast_all=False)
    run.message_ids = ids
    db.add(AuditLog(entity_type='ticket', entity_id=ticket.id, action='automation_applied', user_id=None,
                   changes={'rule_id': rule.id, 'rule_name': rule.name, 'run_id': run.id}))


def run_automation_rules(db: Session, now=None):
    from app.services.channel_queue import DeferredCommitSession
    now = now or datetime.now(timezone.utc)
    rule_ids = [row[0] for row in db.query(AutomationRule.id).filter(AutomationRule.is_active.is_(True)).order_by(AutomationRule.id)]
    touched, handled = 0, set()
    for rule_id in rule_ids:
        rule = db.get(AutomationRule, rule_id)
        candidates = [row[0] for row in _candidates(db, rule).with_entities(Ticket.id).order_by(Ticket.id)]
        for ticket_id in candidates:
            rule = db.query(AutomationRule).filter_by(id=rule_id, is_active=True).populate_existing().with_for_update(skip_locked=True).first()
            if rule is None:
                break
            if ticket_id in handled:
                continue
            ticket = _candidates(db, rule).filter(Ticket.id == ticket_id).populate_existing().with_for_update(skip_locked=True).first()
            if ticket is None:
                continue
            episode = _episode(db, rule, ticket, now)
            next_run = _next_run(db, rule, ticket, episode, now) if episode else None
            if next_run is None:
                continue
            occurrence, previous = next_run
            previous_id = previous.id if previous else None
            try:
                error = _preflight(db, rule, ticket)
                if error:
                    raise ValueError(error)
                with DeferredCommitSession(bind=db.connection(), join_transaction_mode='create_savepoint') as unit:
                    current_rule, current_ticket = unit.get(AutomationRule, rule_id), unit.get(Ticket, ticket_id)
                    run = unit.get(AutomationRun, previous_id) if previous_id else AutomationRun(rule_id=rule_id, ticket_id=ticket_id,
                        revision=rule.revision, episode=episode, occurrence=occurrence, created_at=now)
                    run.state, run.error, run.available_at = 'applied', None, None
                    run.attempts = (run.attempts or 0) + 1
                    unit.add(run); unit.flush()
                    _apply(unit, current_rule, current_ticket, run)
                    Session.commit(unit)
                db.commit(); db.expire_all()
                touched += 1
                if any(a['type'] == 'change_status' for a in _actions(rule)):
                    handled.add(ticket_id)
            except Exception as exc:
                # All actions/outbox records were rolled back together. Log a safe
                # error and limit automatic retries; provider retries live elsewhere.
                db.expire_all()
                rule = db.get(AutomationRule, rule_id)
                run = db.get(AutomationRun, previous_id) if previous_id else AutomationRun(rule_id=rule_id, ticket_id=ticket_id,
                    revision=rule.revision, episode=episode, occurrence=occurrence, created_at=now)
                run.state, run.message_ids = 'error', []
                run.error = str(exc)[:500] if isinstance(exc, ValueError) else f'Ошибка выполнения ({type(exc).__name__})'
                run.attempts = (run.attempts or 0) + 1
                run.available_at = now + timedelta(hours=1)
                db.add(run); db.commit()
    db.commit()
    return touched
