"""Живые уведомления: аутентификация websocket и фан-аут через LISTEN/NOTIFY.

Основное здесь — разграничение: портальный токен клиента не должен открывать
ленту уведомлений сотрудника. Отдельно проверяется код закрытия: при отказе
он обязан быть 1008, потому что фронтенд по нему отличает «токен не тот» от
оборванной сети и переподключается по разному расписанию.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token, create_portal_access_token
from app.main import app
from app.models.contact import Contact
from app.models.user import User
from app.services.realtime import NotificationHub


@pytest.fixture()
def client():
    # Websocket поднимается только внутри контекста TestClient: без него не
    # запускается lifespan, а вместе с ним — фоновая задача LISTEN.
    with TestClient(app) as test_client:
        yield test_client


def _expect_rejected(client: TestClient, token: str) -> None:
    with client.websocket_connect(f"/ws/notifications?token={token}") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
    # Именно 1008, а не 1006: по коду фронтенд отличает отказ в доступе от
    # оборванной сети. Ради этого соединение сначала принимается и только
    # потом закрывается — закрытие до accept() даёт браузеру бессмысленный 1006.
    assert exc.value.code == 1008


def test_socket_requires_a_token(client: TestClient):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/notifications"):
            pass


def test_socket_rejects_garbage_token(client: TestClient):
    _expect_rejected(client, "не-токен")


def test_socket_rejects_portal_token(client: TestClient, contact: Contact):
    """Клиент с токеном личного кабинета не должен подписаться на ленту
    сотрудника — иначе он увидит внутренние уведомления по чужим заявкам."""
    _expect_rejected(client, create_portal_access_token(contact.id))


def test_socket_rejects_unknown_user(client: TestClient):
    """Подписанный токен несуществующего пользователя: подпись верна, но
    учётной записи нет — доступа быть не должно."""
    _expect_rejected(client, create_access_token(10_000_000, "engineer"))


def test_socket_accepts_staff_token(client: TestClient, db: Session):
    # Берётся реально существующий сотрудник из сида, а не фикстура: тест
    # работает в откатываемой транзакции, и созданного в ней пользователя
    # приложение своим соединением всё равно не увидит.
    staff = db.query(User).filter(User.is_active.is_(True)).first()
    assert staff is not None, "выполните `python -m app.seed` перед тестами"

    token = create_access_token(staff.id, staff.role.value)
    with client.websocket_connect(f"/ws/notifications?token={token}") as ws:
        # Сокет только для сервер→клиент, поэтому проверяется сам факт того,
        # что соединение живо и не закрылось сразу.
        ws.close()


# --- фан-аут ------------------------------------------------------------


class _FakeSocket:
    """Подменяет WebSocket: хабу от него нужны только accept() и send_json()."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        pass

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def test_hub_delivers_only_to_the_addressee():
    async def scenario():
        hub = NotificationHub()
        mine, theirs = _FakeSocket(), _FakeSocket()
        await hub.connect(1, mine)
        await hub.connect(2, theirs)
        await hub._fan_out(1, {"user_id": 1, "title": "SLA 75%"})
        return mine, theirs

    mine, theirs = asyncio.run(scenario())
    assert [n["title"] for n in mine.sent] == ["SLA 75%"]
    # Чужой сокет не должен получить ничего: уведомления адресные.
    assert theirs.sent == []


def test_hub_delivers_to_every_tab_of_one_user():
    async def scenario():
        hub = NotificationHub()
        first, second = _FakeSocket(), _FakeSocket()
        await hub.connect(1, first)
        await hub.connect(1, second)
        await hub._fan_out(1, {"user_id": 1, "title": "Назначена заявка"})
        return first, second

    first, second = asyncio.run(scenario())
    # У сотрудника часто открыто несколько вкладок; отстающая вкладка со
    # старым счётчиком читается как «уведомление потерялось».
    assert len(first.sent) == 1 and len(second.sent) == 1


def test_disconnect_removes_the_socket():
    async def scenario():
        hub = NotificationHub()
        socket = _FakeSocket()
        await hub.connect(1, socket)
        hub.disconnect(1, socket)
        await hub._fan_out(1, {"user_id": 1, "title": "После отключения"})
        return socket

    assert asyncio.run(scenario()).sent == []


def test_broken_socket_is_dropped_and_does_not_block_the_others():
    """Мёртвая вкладка не должна съедать уведомление у живых и не должна
    копиться в памяти процесса."""

    class _BrokenSocket(_FakeSocket):
        async def send_json(self, payload: dict) -> None:
            raise RuntimeError("сокет уже закрыт")

    async def scenario():
        hub = NotificationHub()
        broken, alive = _BrokenSocket(), _FakeSocket()
        await hub.connect(1, broken)
        await hub.connect(1, alive)
        await hub._fan_out(1, {"user_id": 1, "title": "Проверка живучести"})
        return hub, broken, alive

    hub, broken, alive = asyncio.run(scenario())
    assert len(alive.sent) == 1
    assert broken not in hub._connections.get(1, set())
