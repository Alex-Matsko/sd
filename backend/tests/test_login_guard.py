"""Защита входа от перебора пароля.

Панель и портал смотрят в интернет, а вход не был ограничен ничем: ни числом
попыток, ни задержкой. Проверяется, что блокировка наступает, что удачный
вход её снимает и что честный пользователь под неё не попадает.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.deps import check_login_allowed
from app.services.login_guard import MAX_ATTEMPTS, guard


@pytest.fixture(autouse=True)
def clean_guard():
    # Счётчик живёт в процессе и иначе протёк бы между тестами.
    guard.reset()
    yield
    guard.reset()


def test_login_is_open_until_the_limit():
    for _ in range(MAX_ATTEMPTS - 1):
        guard.register_failure("staff", "someone@test.local", "10.0.0.1")
    check_login_allowed("staff", "someone@test.local", "10.0.0.1")


def test_login_locks_after_the_limit():
    for _ in range(MAX_ATTEMPTS):
        guard.register_failure("staff", "someone@test.local", "10.0.0.1")

    with pytest.raises(HTTPException) as exc:
        check_login_allowed("staff", "someone@test.local", "10.0.0.1")
    # 429, а не 401: иначе клиент решит, что дело в пароле, и будет пробовать
    # дальше, продлевая блокировку.
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


def test_a_successful_login_clears_the_counter():
    """Несколько опечаток подряд с последующим верным паролем — обычное
    поведение человека, а не атака."""
    for _ in range(MAX_ATTEMPTS - 1):
        guard.register_failure("staff", "someone@test.local", "10.0.0.1")
    guard.register_success("staff", "someone@test.local", "10.0.0.1")

    for _ in range(MAX_ATTEMPTS - 1):
        guard.register_failure("staff", "someone@test.local", "10.0.0.1")
    check_login_allowed("staff", "someone@test.local", "10.0.0.1")


def test_lockout_by_address_does_not_touch_other_addresses():
    for _ in range(MAX_ATTEMPTS):
        guard.register_failure("staff", "victim@test.local", "")

    check_login_allowed("staff", "another@test.local", "")


def test_lockout_by_ip_stops_walking_through_addresses():
    """Блокировка только по адресу позволила бы перебирать разные адреса с
    одного узла."""
    for i in range(MAX_ATTEMPTS):
        guard.register_failure("staff", f"user{i}@test.local", "10.0.0.7")

    with pytest.raises(HTTPException):
        check_login_allowed("staff", "fresh@test.local", "10.0.0.7")


def test_scopes_are_independent():
    """Перебор портала не должен закрывать вход сотрудникам."""
    for _ in range(MAX_ATTEMPTS):
        guard.register_failure("portal", "client@test.local", "10.0.0.8")

    check_login_allowed("staff", "client@test.local", "10.0.0.8")


def test_unknown_address_costs_the_same_as_a_known_one(db: Session):
    """Тайминг-оракул: без проверки пароля для несуществующего адреса ответ
    приходил заметно быстрее, и по времени перебирались существующие учётки."""
    import time

    from app.core.security import DUMMY_PASSWORD_HASH, verify_password
    from app.models.user import User

    real = db.query(User).first()
    assert real is not None

    start = time.perf_counter()
    verify_password("wrong-password", real.password_hash)
    known = time.perf_counter() - start

    start = time.perf_counter()
    verify_password("wrong-password", DUMMY_PASSWORD_HASH)
    unknown = time.perf_counter() - start

    # Порядок величины один и тот же — обе проверки реально считают bcrypt.
    assert 0.2 < unknown / known < 5
