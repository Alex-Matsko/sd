"""Versioned project plans, task dependencies and staff/client approval rounds."""
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.enums import NotificationType, UserRole
from app.models.audit import AuditLog
from app.models.contact import Contact
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.ticket import Ticket
from app.models.user import User
from app.models.work import WorkApproval, WorkComment, WorkDependency, WorkProject, WorkTask, WorkTicketLink
from app.schemas.work import ProjectCreate
from app.services import audit, realtime, ticket_access

PLAN_STATES = {'draft', 'planning'}
TERMINAL_TASKS = {'done', 'cancelled'}
PLAN_FIELDS = {'title', 'description', 'stage', 'assignee_id', 'start_date', 'due_date', 'estimate_minutes', 'depends_on_ids'}
TRANSITIONS = {
    'draft': {'planning', 'cancelled'},
    'planning': {'cancelled'},
    'approval': {'planning', 'cancelled'},
    'approved': {'planning', 'in_progress', 'cancelled'},
    'in_progress': {'planning', 'paused', 'completed', 'cancelled'},
    'paused': {'planning', 'in_progress', 'cancelled'},
    'completed': {'planning'},
    'cancelled': {'planning'},
}


def fail(message, code=422):
    raise HTTPException(status_code=code, detail=message)


def can_manage(actor, project):
    return actor.role in (UserRole.ADMIN, UserRole.MANAGER) or project.owner_id == actor.id


def visible_query(db, actor):
    query = db.query(WorkProject)
    if ticket_access.sees_full_queue(actor):
        return query
    return query.filter(or_(WorkProject.owner_id == actor.id,
        WorkProject.id.in_(db.query(WorkTask.project_id).filter(WorkTask.assignee_id == actor.id)),
        WorkProject.id.in_(db.query(WorkApproval.project_id).filter(WorkApproval.user_id == actor.id))))


def get_project(db, project_id, actor=None, version=None, manage=False):
    query = visible_query(db, actor) if actor else db.query(WorkProject)
    query = query.filter(WorkProject.id == project_id)
    if version is not None:
        query = query.with_for_update(of=WorkProject)
    project = query.populate_existing().first()
    if project is None:
        fail('Проект не найден', 404)
    if manage and not can_manage(actor, project):
        fail('Изменять план может руководитель проекта или менеджер', 403)
    if version is not None and version != project.version:
        fail('Проект изменился. Обновите данные и повторите действие', 409)
    return project


def active_user(db, user_id):
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        fail('Сотрудник не найден или отключён')
    return user


def check_dates(start, due, project=None):
    if start and due and due < start:
        fail('Срок окончания не может быть раньше начала')
    if project:
        if project.start_date and ((start and start < project.start_date) or (due and due < project.start_date)):
            fail('Задача начинается раньше проекта')
        if project.due_date and ((due and due > project.due_date) or (start and start > project.due_date)):
            fail('Задача выходит за срок проекта')


def require_plan(project):
    if project.status not in PLAN_STATES:
        fail('Для изменения плана верните проект в планирование: потребуется повторное согласование', 409)


def notify(db, project, user_ids, type_, title):
    for user_id in set(user_ids):
        db.add(Notification(user_id=user_id, project_id=project.id, type=type_, title=title[:500]))
        realtime.publish_notification(db, user_id, type_.value, title[:500], None)


def record(db, project, action, actor=None, changes=None):
    project.version += 1
    project.updated_at = datetime.now(timezone.utc)
    audit.record(db, entity_type='work_project', entity_id=project.id, action=action,
                 user_id=actor.id if actor else None, changes=changes)


def create_project(db, payload: ProjectCreate, actor):
    owner = active_user(db, payload.owner_id or actor.id)
    if owner.id != actor.id and actor.role not in (UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER):
        fail('Назначить другого руководителя может диспетчер или менеджер', 403)
    if payload.organization_id is not None and db.get(Organization, payload.organization_id) is None:
        fail('Организация не найдена')
    check_dates(payload.start_date, payload.due_date)
    project = WorkProject(**payload.model_dump(exclude={'owner_id'}), owner_id=owner.id)
    db.add(project)
    db.flush()
    audit.record(db, entity_type='work_project', entity_id=project.id, action='created', user_id=actor.id,
                 changes={'title': project.title})
    if owner.id != actor.id:
        notify(db, project, [owner.id], NotificationType.WORK_ASSIGNED, f'Вы руководите проектом: {project.title}')
    db.commit()
    return project


def dependencies(db, project):
    ids = [t.id for t in project.tasks]
    edges = db.query(WorkDependency).filter(WorkDependency.task_id.in_(ids)).all() if ids else []
    return {t.id: [e.depends_on_id for e in edges if e.task_id == t.id] for t in project.tasks}


def validate_graph(db, project, task_id=None, proposed=None):
    graph = dependencies(db, project)
    if task_id is not None:
        if any(i not in graph for i in proposed):
            fail('Зависимости должны принадлежать этому проекту')
        graph[task_id] = list(set(proposed))
    visiting, done = set(), set()

    def visit(node):
        if node in visiting:
            fail('Зависимость создаёт цикл')
        if node in done:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        done.add(node)
    for key in graph:
        visit(key)
    return graph


def update_project(db, project, payload, actor):
    require_plan(project)
    values = payload.model_dump(exclude={'version'}, exclude_unset=True)
    if 'owner_id' in values:
        active_user(db, values['owner_id'])
    start, due = values.get('start_date', project.start_date), values.get('due_date', project.due_date)
    check_dates(start, due)
    for task in project.tasks:
        if task.status == 'cancelled':
            continue
        if start and ((task.start_date and task.start_date < start) or (task.due_date and task.due_date < start)):
            fail('Новый срок проекта исключает запланированные задачи')
        if due and ((task.due_date and task.due_date > due) or (task.start_date and task.start_date > due)):
            fail('Новый срок проекта исключает запланированные задачи')
    old_owner = project.owner_id
    for key, value in values.items():
        setattr(project, key, value)
    record(db, project, 'plan_updated', actor, {k: str(v) if isinstance(v, date) else v for k, v in values.items()})
    if old_owner != project.owner_id:
        notify(db, project, [project.owner_id], NotificationType.WORK_ASSIGNED, f'Вы руководите проектом: {project.title}')
    db.commit()


def create_task(db, project, payload, actor):
    require_plan(project)
    values = payload.model_dump(exclude={'version', 'depends_on_ids'})
    if payload.assignee_id:
        active_user(db, payload.assignee_id)
    check_dates(payload.start_date, payload.due_date, project)
    if any(i not in {t.id for t in project.tasks} for i in payload.depends_on_ids):
        fail('Зависимости должны принадлежать этому проекту')
    task = WorkTask(project_id=project.id, **values)
    db.add(task)
    db.flush()
    for dependency in set(payload.depends_on_ids):
        db.add(WorkDependency(task_id=task.id, depends_on_id=dependency))
    record(db, project, 'task_created', actor, {'task_id': task.id, 'title': task.title})
    if task.assignee_id and task.assignee_id != actor.id:
        notify(db, project, [task.assignee_id], NotificationType.WORK_ASSIGNED, f'Задача «{task.title}» в проекте «{project.title}»')
    db.commit()


def update_task(db, project, task_id, payload, actor):
    task = next((t for t in project.tasks if t.id == task_id), None)
    if task is None:
        fail('Задача не найдена', 404)
    manager = can_manage(actor, project)
    if not manager and task.assignee_id != actor.id:
        fail('Изменять задачу может её исполнитель или руководитель проекта', 403)
    values = payload.model_dump(exclude={'version'}, exclude_unset=True)
    plan_change = bool(PLAN_FIELDS & values.keys()) or values.get('status') == 'cancelled'
    if plan_change:
        if not manager:
            fail('План меняет руководитель проекта', 403)
        require_plan(project)
    if 'assignee_id' in values and values['assignee_id']:
        active_user(db, values['assignee_id'])
    check_dates(values.get('start_date', task.start_date), values.get('due_date', task.due_date), project)
    graph = validate_graph(db, project, task.id, values['depends_on_ids']) if 'depends_on_ids' in values else dependencies(db, project)
    status = values.get('status', task.status)
    changed_scope = any(key in values and values[key] != getattr(task, key) for key in PLAN_FIELDS - {'depends_on_ids'})
    if 'depends_on_ids' in values:
        changed_scope = changed_scope or set(values['depends_on_ids']) != set(dependencies(db, project)[task.id])
    if changed_scope and task.status in ('in_progress', 'review', 'done') and status not in ('backlog', 'ready'):
        fail('Перед изменением начатой или принятой задачи верните её в план', 409)
    if status != task.status:
        if project.status in PLAN_STATES:
            if not manager or status not in ('backlog', 'ready', 'cancelled'):
                fail('До согласования задачи можно только планировать', 409)
        elif project.status != 'in_progress':
            fail('Задачи можно выполнять только в проекте «В работе»', 409)
        allowed = {
            'backlog': {'ready', 'in_progress', 'cancelled'},
            'ready': {'backlog', 'in_progress', 'cancelled'},
            'in_progress': {'ready', 'review'},
            'review': {'in_progress', 'done'},
            'done': {'ready'},
            'cancelled': {'backlog', 'ready'},
        }
        if project.status not in PLAN_STATES and status not in allowed[task.status]:
            fail('Недопустимый переход статуса задачи', 409)
        if task.status == 'done' and not manager:
            fail('Возвращает принятую задачу руководитель проекта', 403)
        if status == 'done':
            if not manager:
                fail('Принимает результат руководитель проекта', 403)
            if len(values.get('completion_note', task.completion_note).strip()) < 3:
                fail('Опишите результат выполнения перед приёмкой')
        if status in ('in_progress', 'review', 'done'):
            by_id = {t.id: t for t in project.tasks}
            if any(by_id[i].status != 'done' for i in graph[task.id]):
                fail('Сначала завершите предшествующие задачи', 409)
            if task.assignee_id is None:
                fail('Назначьте исполнителя')
        if task.status == 'done':
            by_id = {t.id: t for t in project.tasks}
            if any(task.id in deps and by_id[i].status in ('in_progress', 'review', 'done') for i, deps in graph.items()):
                fail('Сначала верните зависимые задачи в план', 409)
    if task.status == 'done' and status == 'done' and any(key in values and values[key] != getattr(task, key) for key in ('actual_minutes', 'completion_note')):
        fail('Для изменения принятого результата сначала верните задачу в работу', 409)
    if ('actual_minutes' in values or 'completion_note' in values) and project.status in ('approval', 'approved', 'completed', 'cancelled'):
        fail('В текущем состоянии проекта нельзя менять результаты задач', 409)
    old_assignee, old_status = task.assignee_id, task.status
    for key, value in values.items():
        if key != 'depends_on_ids':
            setattr(task, key, value)
    if changed_scope:
        task.completion_note = ''
    if status != 'done':
        task.completed_at = None
    elif task.completed_at is None:
        task.completed_at = datetime.now(timezone.utc)
    if 'depends_on_ids' in values:
        db.query(WorkDependency).filter_by(task_id=task.id).delete()
        for dependency in set(values['depends_on_ids']):
            db.add(WorkDependency(task_id=task.id, depends_on_id=dependency))
    record(db, project, 'task_updated', actor, {'task_id': task.id, **{k: str(v) if isinstance(v, date) else v for k, v in values.items()}})
    if task.assignee_id and old_assignee != task.assignee_id:
        notify(db, project, [task.assignee_id], NotificationType.WORK_ASSIGNED, f'Задача «{task.title}» в проекте «{project.title}»')
    if status == 'review' and old_status != 'review':
        notify(db, project, [project.owner_id], NotificationType.WORK_UPDATED, f'На проверке: {task.title} / {project.title}')
    db.commit()


def transition(db, project, payload, actor):
    if payload.status not in TRANSITIONS[project.status]:
        fail('Недопустимый переход состояния проекта', 409)
    if payload.status in ('planning', 'cancelled') and project.status not in PLAN_STATES and len(payload.reason.strip()) < 3:
        fail('Укажите причину изменения согласованного плана')
    if payload.status == 'completed':
        if not project.tasks or any(t.status not in TERMINAL_TASKS for t in project.tasks):
            fail('Сначала завершите или отмените все задачи', 409)
    if payload.status == 'in_progress':
        active_user(db, project.owner_id)
    if payload.status in ('planning', 'cancelled'):
        for approval in project.approvals:
            if approval.state == 'pending':
                approval.state = 'superseded'
    old = project.status
    project.status = payload.status
    record(db, project, 'status_changed', actor, {'from': old, 'to': payload.status, 'reason': payload.reason})
    recipients = {t.assignee_id for t in project.tasks if t.assignee_id} | {project.owner_id}
    notify(db, project, recipients - {actor.id}, NotificationType.WORK_UPDATED, f'Изменилось состояние проекта: {project.title}')
    db.commit()


def snapshot(db, project):
    deps = dependencies(db, project)
    users = {u.id: u.full_name for u in db.query(User).filter(User.id.in_({project.owner_id} | {t.assignee_id for t in project.tasks if t.assignee_id}))}
    return {'title': project.title, 'description': project.description, 'owner_name': users.get(project.owner_id),
            'start_date': str(project.start_date) if project.start_date else None,
            'due_date': str(project.due_date) if project.due_date else None,
            'plan_version': project.version,
            'tasks': [{'id': t.id, 'title': t.title, 'description': t.description, 'stage': t.stage,
                       'assignee_name': users.get(t.assignee_id), 'estimate_minutes': t.estimate_minutes,
                       'start_date': str(t.start_date) if t.start_date else None,
                       'due_date': str(t.due_date) if t.due_date else None, 'depends_on_ids': deps[t.id]}
                      for t in project.tasks if t.status != 'cancelled']}


def request_approval(db, project, payload, actor):
    require_plan(project)
    if not project.due_date:
        fail('Укажите срок проекта перед согласованием')
    active_user(db, project.owner_id)
    tasks = [t for t in project.tasks if t.status != 'cancelled']
    if not tasks:
        fail('Добавьте хотя бы одну задачу в план')
    graph = validate_graph(db, project)
    by_id = {t.id: t for t in project.tasks}
    for task in tasks:
        if not task.assignee_id or not task.due_date:
            fail('Для каждой задачи нужны исполнитель и срок')
        active_user(db, task.assignee_id)
        check_dates(task.start_date, task.due_date, project)
        for dep_id in graph[task.id]:
            dep = by_id[dep_id]
            if task.status in ('in_progress', 'review', 'done') and dep.status != 'done':
                fail('Верните начатую задачу в план: её предшественник ещё не принят')
            if dep.status == 'cancelled':
                fail('В плане есть зависимость от отменённой задачи')
            if dep.due_date and task.start_date and dep.due_date > task.start_date:
                fail('Предшествующая задача заканчивается позже начала зависимой')
    users = [active_user(db, i) for i in set(payload.user_ids)]
    if any(u.id in (actor.id, project.owner_id) for u in users):
        fail('Согласующий сотрудник должен отличаться от руководителя и инициатора согласования')
    if project.organization_id is not None and not payload.contact_ids:
        fail('Для проекта организации выберите представителя клиента для согласования')
    contacts = []
    for contact_id in set(payload.contact_ids):
        contact = db.get(Contact, contact_id)
        if contact is None or not project.organization_id or contact.organization_id != project.organization_id:
            fail('Представитель клиента должен принадлежать организации проекта')
        contacts.append(contact)
    plan = snapshot(db, project)
    project.approval_round += 1
    for user in users:
        db.add(WorkApproval(project_id=project.id, round=project.approval_round, user_id=user.id,
                            approver_name=user.full_name, snapshot=plan))
    for contact in contacts:
        db.add(WorkApproval(project_id=project.id, round=project.approval_round, contact_id=contact.id,
                            approver_name=contact.full_name, snapshot=plan))
    project.status = 'approval'
    record(db, project, 'approval_requested', actor, {'round': project.approval_round, 'user_ids': payload.user_ids, 'contact_ids': payload.contact_ids})
    notify(db, project, payload.user_ids, NotificationType.WORK_APPROVAL, f'Требуется согласование проекта: {project.title}')
    db.commit()


def decide(db, project, approval_id, payload, actor=None, contact=None):
    approval = next((a for a in project.approvals if a.id == approval_id), None)
    if approval is None:
        fail('Согласование не найдено', 404)
    if actor and approval.user_id != actor.id:
        fail('Решение принимает только назначенный согласующий', 403)
    if contact and (approval.contact_id != contact.id or project.organization_id != contact.organization_id):
        fail('Согласование не найдено', 404)
    if project.status != 'approval' or approval.round != project.approval_round or approval.state != 'pending':
        fail('Этот круг согласования уже завершён или отменён', 409)
    if payload.decision == 'rejected' and len(payload.comment.strip()) < 3:
        fail('Укажите замечания для доработки')
    approval.state, approval.comment = payload.decision, payload.comment
    approval.decided_at = datetime.now(timezone.utc)
    current = [a for a in project.approvals if a.round == project.approval_round]
    if payload.decision == 'rejected':
        project.status = 'planning'
        for other in current:
            if other.state == 'pending':
                other.state = 'superseded'
    elif all(a.state == 'approved' for a in current):
        project.status = 'approved'
    record(db, project, 'approval_decided', actor, {'approval_id': approval.id, 'round': approval.round,
           'decision': payload.decision, 'comment': payload.comment, 'contact_id': contact.id if contact else None})
    notify(db, project, [project.owner_id], NotificationType.WORK_APPROVAL, f'Получено решение по проекту: {project.title}')
    db.commit()


def project_view(db, project, actor, detail=True):
    tasks = project.tasks
    active = [t for t in tasks if t.status != 'cancelled']
    done = sum(t.status == 'done' for t in active)
    today = date.today()
    result = {key: getattr(project, key) for key in ('id', 'title', 'description', 'organization_id', 'owner_id', 'status', 'start_date', 'due_date', 'version', 'approval_round', 'created_at', 'updated_at')}
    result.update(task_count=len(active), completed_count=done, progress_pct=round(done * 100 / len(active)) if active else 0,
                  estimate_minutes=sum(t.estimate_minutes for t in active), actual_minutes=sum(t.actual_minutes for t in tasks),
                  overdue=bool(project.due_date and project.due_date < today and project.status not in ('completed', 'cancelled')),
                  can_manage=can_manage(actor, project))
    if not detail:
        return result
    deps = dependencies(db, project)
    by_id = {t.id: t for t in tasks}
    result['tasks'] = [{**{key: getattr(t, key) for key in ('id', 'title', 'description', 'stage', 'status', 'assignee_id', 'start_date', 'due_date', 'estimate_minutes', 'actual_minutes', 'completion_note', 'completed_at')},
                        'depends_on_ids': deps[t.id], 'blocked': any(by_id[i].status != 'done' for i in deps[t.id]),
                        'overdue': bool(t.due_date and t.due_date < today and t.status not in TERMINAL_TASKS)} for t in tasks]
    result['approvals'] = [{key: getattr(a, key) for key in ('id', 'round', 'user_id', 'contact_id', 'approver_name', 'state', 'snapshot', 'comment', 'requested_at', 'decided_at')} for a in project.approvals]
    ticket_ids = db.query(WorkTicketLink.ticket_id).filter_by(project_id=project.id)
    # Project membership never bypasses the existing ticket access boundary.
    result['tickets'] = [{'id': t.id, 'display_number': t.display_number, 'subject': t.subject, 'status': t.status}
                         for t in ticket_access.visible_tickets_query(db, actor).filter(Ticket.id.in_(ticket_ids))]
    comments = db.query(WorkComment, User.full_name).join(User, User.id == WorkComment.user_id).filter(WorkComment.project_id == project.id).order_by(WorkComment.id.desc()).limit(100).all()
    result['comments'] = [{'id': c.id, 'user_id': c.user_id, 'author_name': name, 'body': c.body, 'created_at': c.created_at} for c, name in comments]
    history = db.query(AuditLog, User.full_name).outerjoin(User, User.id == AuditLog.user_id).filter(AuditLog.entity_type == 'work_project', AuditLog.entity_id == project.id).order_by(AuditLog.id.desc()).limit(100).all()
    result['history'] = [{'id': a.id, 'action': a.action, 'author_name': name, 'changes': a.changes, 'created_at': a.created_at} for a, name in history]
    return result
