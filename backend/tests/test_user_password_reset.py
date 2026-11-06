"""Administrative password reset must replace login credentials without leaking them."""
import json

import pytest
from fastapi.testclient import TestClient

from app.core.enums import UserRole
from app.core.security import create_access_token, hash_password, verify_password
from app.db import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.user import User


@pytest.fixture()
def client(db):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous


def headers(user):
    return {'Authorization': 'Bearer ' + create_access_token(user.id, user.role.value)}


def test_admin_reset_replaces_password_revokes_refresh_and_redacts_audit(client, db, engineer_user):
    admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
    old_login = client.post('/auth/login', data={'username': engineer_user.email, 'password': 'test123'})
    assert old_login.status_code == 200
    old_refresh = old_login.json()['refresh_token']
    response = client.patch(f'/users/{engineer_user.id}', headers=headers(admin), json={'password': 'ResetForTest123!'})
    assert response.status_code == 200
    assert 'password' not in response.json() and 'password_hash' not in response.json()
    assert client.post('/auth/login', data={'username': engineer_user.email, 'password': 'test123'}).status_code == 401
    assert client.post('/auth/login', data={'username': engineer_user.email, 'password': 'ResetForTest123!'}).status_code == 200
    assert client.post('/auth/refresh', json={'refresh_token': old_refresh}).status_code == 401
    entries = db.query(AuditLog).filter_by(entity_type='user', entity_id=engineer_user.id, user_id=admin.id).all()
    assert any(e.changes.get('password_hash') == 'изменено' for e in entries)
    assert 'ResetForTest123!' not in json.dumps([e.changes for e in entries])


@pytest.mark.parametrize('role', [UserRole.ENGINEER, UserRole.DISPATCHER, UserRole.MANAGER])
def test_non_admin_cannot_reset_admin_password(client, db, role):
    admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
    actor = User(full_name='Restricted reset actor', email='restricted-reset@example.com', password_hash=hash_password('OldPassword123!'), role=role)
    db.add(actor); db.commit()
    before = admin.password_hash
    response = client.patch(f'/users/{admin.id}', headers=headers(actor), json={'password': 'ForbiddenReset123!'})
    assert response.status_code == 403
    db.refresh(admin)
    assert admin.password_hash == before


def test_short_reset_is_rejected_without_changing_employee(client, db, engineer_user):
    admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
    response = client.patch(f'/users/{engineer_user.id}', headers=headers(admin), json={'password': 'short'})
    assert response.status_code == 422
    db.refresh(engineer_user)
    assert verify_password('test123', engineer_user.password_hash)
