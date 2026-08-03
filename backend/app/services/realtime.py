"""Real-time in-app notifications over WebSocket (ТЗ р. 8: "Уведомления
инженерам: в интерфейсе (websocket)").

Notifications are created by the *worker* process (SLA escalations), while
WebSockets are held by the *app* process - so the two need a channel between
them. That channel is PostgreSQL's own LISTEN/NOTIFY rather than Redis:
the database is already there, already shared by both processes, and
`pg_notify` fires on commit, which means a client is never woken up for a
notification row that isn't visible yet. README has anticipated Redis for
this since Stage 1; it turned out not to be needed.

If the listener connection dies the hub reconnects, and the client keeps its
30-second polling as a fallback - so a websocket outage degrades to the old
behaviour instead of silently dropping notifications.
"""

import asyncio
import json
import logging

import psycopg
from fastapi import WebSocket

from app.config import settings

logger = logging.getLogger("app.realtime")

CHANNEL = "sd_notifications"
_RECONNECT_DELAY_SECONDS = 5


def _dsn() -> str:
    """SQLAlchemy's URL carries a driver prefix psycopg's own connect() won't
    take, so it's stripped here rather than configured twice."""
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://")


class NotificationHub:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = {}
        self._task: asyncio.Task | None = None

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        sockets = self._connections.get(user_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(user_id, None)

    async def _fan_out(self, user_id: int, payload: dict) -> None:
        """Sends to every session that user has open (desktop plus phone, say).
        A send failure means the socket is already gone - drop it rather than
        letting a dead connection accumulate."""
        dead = []
        for websocket in list(self._connections.get(user_id, ())):
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(user_id, websocket)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._listen_forever())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _listen_forever(self) -> None:
        while True:
            try:
                await self._listen_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Realtime: соединение LISTEN потеряно, переподключение через %s с", _RECONNECT_DELAY_SECONDS)
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)

    async def _listen_once(self) -> None:
        async with await psycopg.AsyncConnection.connect(_dsn(), autocommit=True) as conn:
            await conn.execute(f"LISTEN {CHANNEL}")
            logger.info("Realtime: слушаем канал %s", CHANNEL)
            async for notify in conn.notifies():
                try:
                    payload = json.loads(notify.payload)
                    user_id = int(payload["user_id"])
                except (ValueError, KeyError, TypeError):
                    logger.warning("Realtime: не разобрать полезную нагрузку %r", notify.payload)
                    continue
                await self._fan_out(user_id, payload)


hub = NotificationHub()


def publish_notification(db, user_id: int, notification_type: str, title: str, ticket_id: int | None) -> None:
    """Announces a notification to whichever app process holds that user's
    socket. Called inside the creating transaction on purpose: `pg_notify`
    only delivers on commit, so a rolled-back escalation never reaches a
    client. Failures are swallowed - a missed real-time ping is cosmetic,
    the notification row itself is what matters and polling will find it."""
    payload = json.dumps(
        {"user_id": user_id, "type": notification_type, "title": title, "ticket_id": ticket_id},
        ensure_ascii=False,
    )
    try:
        from sqlalchemy import text

        db.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": CHANNEL, "payload": payload})
    except Exception:
        logger.exception("Realtime: не удалось отправить уведомление пользователю %s", user_id)
