import logging

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.db import SessionLocal
from app.models.user import User
from app.services.realtime import hub

logger = logging.getLogger("app.ws")

router = APIRouter(tags=["realtime"])


def _authenticate(token: str) -> int | None:
    """Same rules as the REST dependency: a valid, non-expired *staff* access
    token. Portal tokens carry type "portal" and are rejected here, so a
    client can't subscribe to an engineer's notification stream."""
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        return None

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        return user.id if user is not None and user.is_active else None
    finally:
        db.close()


@router.websocket("/ws/notifications")
async def notifications_socket(websocket: WebSocket, token: str = Query(...)) -> None:
    """Live notification feed.

    The token travels as a query parameter because the browser WebSocket API
    cannot set an Authorization header - the standard workaround. It is
    therefore visible in server logs of any proxy in front of this endpoint;
    acceptable because access tokens are short-lived (30 minutes) and the
    socket carries no data beyond notifications the user can already read
    over REST."""
    user_id = _authenticate(token)
    if user_id is None:
        # Accept first, then close with the policy code. Closing before
        # accepting makes Starlette reject the handshake at the HTTP level,
        # and the browser reports a generic 1006 ("abnormal closure") - the
        # client then can't tell a rejected token from a dropped network and
        # reconnects on the wrong schedule. Accepting costs nothing here: no
        # data is ever sent on this socket.
        await websocket.accept()
        await websocket.close(code=1008)
        return

    await hub.connect(user_id, websocket)
    try:
        while True:
            # Nothing is expected from the client; this await is how we notice
            # the socket closing. Any received frame is ignored deliberately -
            # this channel is server-to-client only.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Realtime: ошибка websocket-соединения пользователя %s", user_id)
    finally:
        hub.disconnect(user_id, websocket)
