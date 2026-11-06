"""Acceptance and access-control regressions for planned work."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routers.portal import get_current_contact
from app.core.enums import UserRole
from app.db import get_db
from app.main import app
from app.models.contact import Contact
from app.models.notification import Notification
from app.models.user import User


@pytest.fixture()
def staff(db):
    return db.query(User).filter(User.role == UserRole.ADMIN).first()


@pytest.fixture()
def client(db, staff, contact):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: staff
    app.dependency_overrides[get_current_contact] = lambda: contact
    with TestClient(app) as client:
        yield client
    app.dependency_overrides = previous


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def create(client, contact):
    today = date.today()
    return ok(client.post('/projects', json={'title': 'Обновление инфраструктуры', 'description': 'Ожидаемый результат для клиента',
        'organization_id': contact.organization_id, 'start_date': str(today), 'due_date': str(today + timedelta(days=20))}), 201)


def add_task(client, p, staff, title='Подготовить стенд', dependencies=None):
    return ok(client.post(f"/projects/{p['id']}/tasks", json={'version': p['version'], 'title': title,
        'stage': 'Внедрение', 'assignee_id': staff.id, 'start_date': p['start_date'], 'due_date': p['due_date'],
        'estimate_minutes': 120, 'depends_on_ids': dependencies or []}), 201)


def request(client, p, approver, contact):
    return ok(client.post(f"/projects/{p['id']}/approvals", json={'version': p['version'], 'user_ids': [approver.id], 'contact_ids': [contact.id]}), 201)


def as_staff(user):
    app.dependency_overrides[get_current_user] = lambda: user


def decide(client, p, approval_id, decision='approved', comment=''):
    return ok(client.post(f"/projects/{p['id']}/approvals/{approval_id}/decision", json={'version': p['version'], 'decision': decision, 'comment': comment}))


def approved(client, p, approver, contact, staff):
    p = request(client, p, approver, contact)
    as_staff(approver)
    p = decide(client, p, next(a['id'] for a in p['approvals'] if a['user_id'] and a['round'] == p['approval_round']))
    as_staff(staff)
    a = next(a for a in p['approvals'] if a['contact_id'] and a['round'] == p['approval_round'])
    ok(client.post(f"/portal/project-approvals/{a['id']}/decision", json={'version': p['version'], 'decision': 'approved'}))
    return ok(client.get(f"/projects/{p['id']}"))


def move(client, p, status, reason=''):
    return ok(client.post(f"/projects/{p['id']}/status", json={'version': p['version'], 'status': status, 'reason': reason}))


def task_move(client, p, task_id, status, **values):
    return ok(client.patch(f"/projects/{p['id']}/tasks/{task_id}", json={'version': p['version'], 'status': status, **values}))


def test_staff_and_client_approve_then_execute_and_accept(client, contact, staff, engineer_user, db):
    p = add_task(client, create(client, contact), staff)
    task_id = p['tasks'][0]['id']
    p = request(client, p, engineer_user, contact)
    assert p['status'] == 'approval'
    assert db.query(Notification).filter_by(project_id=p['id'], user_id=engineer_user.id).count() == 1
    as_staff(engineer_user)
    p = decide(client, p, next(a['id'] for a in p['approvals'] if a['user_id'] and a['round'] == p['approval_round']))
    assert p['status'] == 'approval'  # Employee approval alone is insufficient.
    as_staff(staff)
    a = next(a for a in p['approvals'] if a['contact_id'] and a['round'] == p['approval_round'])
    ok(client.post(f"/portal/project-approvals/{a['id']}/decision", json={'version': p['version'], 'decision': 'approved'}))
    p = ok(client.get(f"/projects/{p['id']}"))
    assert p['status'] == 'approved'
    assert p['approvals'][0]['snapshot']['tasks'][0]['estimate_minutes'] == 120
    assert client.patch(f"/projects/{p['id']}", json={'version': p['version'], 'title': 'Подмена плана'}).status_code == 409
    p = move(client, p, 'in_progress')
    assert client.post(f"/projects/{p['id']}/status", json={'version': p['version'], 'status': 'completed'}).status_code == 409
    p = task_move(client, p, task_id, 'in_progress')
    p = task_move(client, p, task_id, 'review', actual_minutes=90, completion_note='Развёрнуто и проверено')
    p = task_move(client, p, task_id, 'done')
    assert p['tasks'][0]['completed_at']
    assert p['progress_pct'] == 100 and p['actual_minutes'] == 90
    p = move(client, p, 'completed')
    assert p['status'] == 'completed'
    assert {h['action'] for h in p['history']} >= {'created', 'approval_requested', 'approval_decided', 'task_updated', 'status_changed'}


def test_rejection_preserves_snapshot_and_new_round_is_required(client, contact, staff, engineer_user):
    p = add_task(client, create(client, contact), staff)
    p = request(client, p, engineer_user, contact)
    old_snapshot = p['approvals'][0]['snapshot']
    as_staff(engineer_user)
    approval_id = next(a['id'] for a in p['approvals'] if a['user_id'] and a['round'] == p['approval_round'])
    assert client.post(f"/projects/{p['id']}/approvals/{approval_id}/decision", json={'version': p['version'], 'decision': 'rejected'}).status_code == 422
    p = decide(client, p, approval_id, 'rejected', 'Добавьте план отката')
    assert p['status'] == 'planning'
    assert next(a for a in p['approvals'] if a['contact_id'])['state'] == 'superseded'
    as_staff(staff)
    p = ok(client.patch(f"/projects/{p['id']}", json={'version': p['version'], 'description': 'Дополнен план отката'}))
    assert p['approvals'][0]['snapshot'] == old_snapshot
    assert client.post(f"/projects/{p['id']}/status", json={'version': p['version'], 'status': 'in_progress'}).status_code == 409
    p = request(client, p, engineer_user, contact)
    assert p['approval_round'] == 2 and len(p['approvals']) == 4
    assert p['approvals'][-1]['snapshot']['description'] == 'Дополнен план отката'


def test_cycle_foreign_dependency_and_stale_version_are_rejected(client, contact, staff):
    p = add_task(client, create(client, contact), staff)
    first = p['tasks'][0]['id']
    old_version = p['version']
    p = add_task(client, p, staff, 'Выполнить перенос', [first])
    second = p['tasks'][1]['id']
    assert client.patch(f"/projects/{p['id']}", json={'version': old_version, 'title': 'Потерянная правка'}).status_code == 409
    for deps in ([first], [second], [99999999]):
        assert client.patch(f"/projects/{p['id']}/tasks/{first}", json={'version': p['version'], 'depends_on_ids': deps}).status_code == 422
    other = add_task(client, create(client, contact), staff)
    assert client.patch(f"/projects/{p['id']}/tasks/{first}", json={'version': p['version'], 'depends_on_ids': [other['tasks'][0]['id']]}).status_code == 422


def test_dates_and_mandatory_approval_plan(client, contact, staff, engineer_user):
    assert client.post('/projects', json={'title': 'Плохие даты', 'start_date': '2026-12-01', 'due_date': '2026-11-01'}).status_code == 422
    p = create(client, contact)
    assert client.post(f"/projects/{p['id']}/approvals", json={'version': p['version'], 'user_ids': [engineer_user.id]}).status_code == 422
    assert client.post(f"/projects/{p['id']}/tasks", json={'version': p['version'], 'title': 'Вне проекта', 'start_date': '2000-01-01'}).status_code == 422
    p = add_task(client, p, staff)
    assert client.post(f"/projects/{p['id']}/approvals", json={'version': p['version'], 'user_ids': [staff.id]}).status_code == 422
    assert client.patch(f"/projects/{p['id']}", json={'version': p['version'], 'title': None}).status_code == 422
    assert client.patch(f"/projects/{p['id']}/tasks/{p['tasks'][0]['id']}", json={'version': p['version'], 'status': None}).status_code == 422


def test_project_visibility_and_assignee_permissions(client, contact, staff, engineer_user):
    p = add_task(client, create(client, contact), staff)
    as_staff(engineer_user)
    assert client.get(f"/projects/{p['id']}").status_code == 404
    assert all(row['id'] != p['id'] for row in ok(client.get('/projects')))
    as_staff(staff)
    task = p['tasks'][0]
    p = ok(client.patch(f"/projects/{p['id']}/tasks/{task['id']}", json={'version': p['version'], 'assignee_id': engineer_user.id}))
    as_staff(engineer_user)
    assert client.get(f"/projects/{p['id']}").status_code == 200
    assert client.patch(f"/projects/{p['id']}", json={'version': p['version'], 'title': 'Чужой план'}).status_code == 403
    assert client.patch(f"/projects/{p['id']}/tasks/{task['id']}", json={'version': p['version'], 'estimate_minutes': 1}).status_code == 403
    assert client.patch(f"/projects/{p['id']}/tasks/{task['id']}", json={'version': p['version'], 'status': 'in_progress'}).status_code == 409


def test_portal_only_named_contact_sees_immutable_scope(client, contact, staff, engineer_user, db):
    p = add_task(client, create(client, contact), staff)
    ok(client.post(f"/projects/{p['id']}/comments", json={'body': 'Внутренние финансовые сведения'}), 201)
    p = request(client, p, engineer_user, contact)
    rows = ok(client.get('/portal/project-approvals'))
    row = next(a for a in rows if a['project_id'] == p['id'])
    assert 'comments' not in row and 'history' not in row and 'tasks' not in row
    assert 'completion_note' not in row['snapshot']['tasks'][0]
    assert 'Внутренние финансовые сведения' not in str(row)
    other = Contact(organization_id=contact.organization_id, full_name='Другой сотрудник клиента')
    db.add(other); db.commit()
    app.dependency_overrides[get_current_contact] = lambda: other
    assert not any(a['project_id'] == p['id'] for a in ok(client.get('/portal/project-approvals')))
    assert client.post(f"/portal/project-approvals/{row['id']}/decision", json={'version': p['version'], 'decision': 'approved'}).status_code == 404


def test_foreign_contact_and_unauthorized_approval_rejected(client, contact, staff, engineer_user, db):
    from app.models.organization import Organization
    org = Organization(name='Другая организация для согласования'); db.add(org); db.flush()
    foreign = Contact(organization_id=org.id, full_name='Чужой клиент'); db.add(foreign); db.commit()
    p = add_task(client, create(client, contact), staff)
    assert client.post(f"/projects/{p['id']}/approvals", json={'version': p['version'], 'user_ids': [engineer_user.id], 'contact_ids': [foreign.id]}).status_code == 422
    p = request(client, p, engineer_user, contact)
    assert client.post(f"/projects/{p['id']}/approvals/{p['approvals'][0]['id']}/decision", json={'version': p['version'], 'decision': 'approved'}).status_code == 403


def test_dependencies_block_execution_and_pause_freezes_board(client, contact, staff, engineer_user):
    p = add_task(client, create(client, contact), staff)
    first = p['tasks'][0]['id']
    p = add_task(client, p, staff, 'Перенос после подготовки', [first])
    second = p['tasks'][1]['id']
    # No contradictory calendar dependency in the agreed plan.
    p = ok(client.patch(f"/projects/{p['id']}/tasks/{second}", json={'version': p['version'], 'start_date': None}))
    p = approved(client, p, engineer_user, contact, staff)
    p = move(client, p, 'in_progress')
    assert client.patch(f"/projects/{p['id']}/tasks/{second}", json={'version': p['version'], 'status': 'in_progress'}).status_code == 409
    p = task_move(client, p, first, 'in_progress')
    p = move(client, p, 'paused')
    assert client.patch(f"/projects/{p['id']}/tasks/{first}", json={'version': p['version'], 'status': 'review'}).status_code == 409
    p = move(client, p, 'in_progress')
    p = task_move(client, p, first, 'review', completion_note='Подготовка завершена')
    p = task_move(client, p, first, 'done')
    p = task_move(client, p, second, 'in_progress')
    assert client.patch(f"/projects/{p['id']}/tasks/{first}", json={'version': p['version'], 'status': 'ready'}).status_code == 409


def test_return_to_planning_invalidates_approval_and_requires_reason(client, contact, staff, engineer_user):
    p = approved(client, add_task(client, create(client, contact), staff), engineer_user, contact, staff)
    assert client.post(f"/projects/{p['id']}/status", json={'version': p['version'], 'status': 'planning'}).status_code == 422
    p = move(client, p, 'planning', 'Расширение объёма работ')
    assert p['status'] == 'planning'
    assert client.post(f"/projects/{p['id']}/status", json={'version': p['version'], 'status': 'in_progress'}).status_code == 409
    assert all(a['state'] == 'approved' for a in p['approvals'])  # Historical decisions remain evidence, not authorization.


def test_ticket_link_uses_existing_visibility_and_organization(client, contact, staff, engineer_user, db):
    from app.schemas.ticket import TicketCreate
    from app.services.tickets import create_ticket
    ticket = create_ticket(db, TicketCreate(contact_id=contact.id, type='incident', channel='phone', subject='Связанное обращение', manual_priority='P3', manual_priority_reason='Проверка'), actor=None)
    ticket.assigned_engineer_id = staff.id; db.commit()
    p = add_task(client, create(client, contact), engineer_user)
    p = ok(client.post(f"/projects/{p['id']}/tickets", json={'version': p['version'], 'ticket_id': ticket.id}), 201)
    assert [t['id'] for t in p['tickets']] == [ticket.id]
    assert [row['id'] for row in ok(client.get(f'/tickets/{ticket.id}/projects'))] == [p['id']]
    as_staff(engineer_user)
    assert ok(client.get(f"/projects/{p['id']}"))['tickets'] == []
    assert client.get(f'/tickets/{ticket.id}/projects').status_code == 404


def test_assignee_submits_but_owner_accepts_and_reopens(client, contact, staff, engineer_user):
    p = add_task(client, create(client, contact), engineer_user)
    task_id = p['tasks'][0]['id']
    p = approved(client, p, engineer_user, contact, staff)
    p = move(client, p, 'in_progress')
    as_staff(engineer_user)
    p = task_move(client, p, task_id, 'in_progress')
    p = task_move(client, p, task_id, 'review', actual_minutes=120, completion_note='Результат представлен')
    assert client.patch(f"/projects/{p['id']}/tasks/{task_id}", json={'version': p['version'], 'status': 'done'}).status_code == 403
    as_staff(staff)
    p = task_move(client, p, task_id, 'done')
    as_staff(engineer_user)
    assert client.patch(f"/projects/{p['id']}/tasks/{task_id}", json={'version': p['version'], 'status': 'ready'}).status_code == 403


def test_client_rejects_and_cannot_decide_an_obsolete_round(client, contact, staff, engineer_user):
    p = request(client, add_task(client, create(client, contact), staff), engineer_user, contact)
    approval = next(a for a in p['approvals'] if a['contact_id'])
    response = ok(client.post(f"/portal/project-approvals/{approval['id']}/decision", json={
        'version': p['version'], 'decision': 'rejected', 'comment': 'Нужен иной срок внедрения'}))
    assert response['project_status'] == 'planning' and not response['can_decide']
    p = ok(client.get(f"/projects/{p['id']}"))
    assert next(a for a in p['approvals'] if a['user_id'])['state'] == 'superseded'
    p = request(client, p, engineer_user, contact)
    assert client.post(f"/portal/project-approvals/{approval['id']}/decision", json={
        'version': p['version'], 'decision': 'approved'}).status_code == 409


def test_accepted_result_cannot_be_rewritten_without_reopening(client, contact, staff, engineer_user):
    p = approved(client, add_task(client, create(client, contact), staff), engineer_user, contact, staff)
    p = move(client, p, 'in_progress')
    task_id = p['tasks'][0]['id']
    p = task_move(client, p, task_id, 'in_progress')
    p = task_move(client, p, task_id, 'review', completion_note='Результат принят', actual_minutes=90)
    p = task_move(client, p, task_id, 'done')
    for values in ({'completion_note': 'Подмена результата'}, {'actual_minutes': 900}):
        assert client.patch(f"/projects/{p['id']}/tasks/{task_id}", json={'version': p['version'], **values}).status_code == 409
    p = task_move(client, p, task_id, 'ready')
    assert p['tasks'][0]['completed_at'] is None


def test_replanning_does_not_keep_acceptance_for_changed_scope(client, contact, staff, engineer_user):
    p = approved(client, add_task(client, create(client, contact), staff), engineer_user, contact, staff)
    p = move(client, p, 'in_progress')
    task_id = p['tasks'][0]['id']
    p = task_move(client, p, task_id, 'in_progress')
    p = task_move(client, p, task_id, 'review', completion_note='Первый объём выполнен')
    p = move(client, p, 'planning', 'Изменение объёма внедрения')
    assert client.patch(f"/projects/{p['id']}/tasks/{task_id}", json={'version': p['version'], 'description': 'Другие критерии готовности'}).status_code == 409
    # A task previously on review can be returned to the plan and re-scoped.
    p = task_move(client, p, task_id, 'ready', description='Другие критерии готовности')
    assert p['tasks'][0]['completion_note'] == ''
    assert p['tasks'][0]['status'] == 'ready'
    assert p['tasks'][0]['description'] == 'Другие критерии готовности'
    p = approved(client, p, engineer_user, contact, staff)
    p = move(client, p, 'in_progress')
    p = task_move(client, p, task_id, 'in_progress')
    p = task_move(client, p, task_id, 'review', completion_note='Новый объём проверен')
    p = task_move(client, p, task_id, 'done')
    p = move(client, p, 'planning', 'Расширение принятой задачи')
    assert client.patch(f"/projects/{p['id']}/tasks/{task_id}", json={'version': p['version'], 'title': 'Дополнительный объём'}).status_code == 409
    p = task_move(client, p, task_id, 'ready', title='Дополнительный объём')
    assert p['tasks'][0]['completed_at'] is None
