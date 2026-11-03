"""Вход канала «Периметр» для служб продукта: облака и издателя.

Защита — общий секрет PERIMETR_SECRET в заголовке X-Webhook-Secret, как у
телефонии и мониторинга. В отличие от них секрет обязателен: без него
канал выключен, а не открыт.
"""

import hmac
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.services import perimetr_channel

router = APIRouter(prefix="/integrations/perimetr", tags=["perimetr"])

KEY_PATTERN = re.compile(r"^(cloud|vms):[0-9a-zA-Z-]{8,72}$")


def require_perimetr_secret(request: Request) -> None:
    expected = settings.perimetr_secret
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Канал «Периметр» не настроен")
    provided = request.headers.get("X-Webhook-Secret") or ""
    if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный секрет")


class PerimetrMessageIn(BaseModel):
    key: str = Field(max_length=80)
    product: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=8000)
    topic: str = Field(default="other", max_length=32)
    name: str = Field(default="", max_length=200)
    customer: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=32)
    email_verified: bool = False
    server: str = Field(default="", max_length=500)
    report: str = Field(default="", max_length=32000)


def _check_key(key: str) -> None:
    if not KEY_PATTERN.match(key):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ключ переписки")


@router.post("/messages", dependencies=[Depends(require_perimetr_secret)])
def post_message(payload: PerimetrMessageIn, db: Session = Depends(get_db)) -> dict:
    _check_key(payload.key)
    if not payload.text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустое сообщение")
    ticket = perimetr_channel.post_message(db, perimetr_channel.Inbound(**payload.model_dump()))
    return {"ticket": ticket.display_number}


@router.get("/conversations/{key}/messages", dependencies=[Depends(require_perimetr_secret)])
def list_messages(key: str, after: int = 0, db: Session = Depends(get_db)) -> dict:
    _check_key(key)
    result = perimetr_channel.list_messages(db, key, max(0, after))
    # Переписки ещё нет — это не ошибка: окно продукта открыто, писать пока
    # не о чем.
    return result or {"tickets": [], "messages": []}
