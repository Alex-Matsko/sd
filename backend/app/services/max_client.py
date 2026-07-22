"""Thin HTTP client over the MAX Bot API (https://dev.max.ru/docs-api).

Endpoints/fields here are transcribed from the public documentation as of
2026-07-22 - there was no reference implementation to adapt (the customer's
prior MAX bridge was never finished) and no live bot token available during
development to verify request/response shapes against. Treat the exact JSON
field names as best-effort until verified against a real bot (see
docs/decisions.md, "Технические примечания по Этапу 5"). All parsing of
inbound shapes is isolated in `max_channel.py` so a field-name correction
there doesn't ripple elsewhere.
"""

import httpx

DEFAULT_BASE_URL = "https://platform-api2.max.ru"


class MaxApiError(RuntimeError):
    pass


def _headers(token: str) -> dict:
    return {"Authorization": token}


def get_updates(
    base_url: str, token: str, marker: int | None, timeout: int = 20, limit: int = 100
) -> tuple[list[dict], int | None]:
    """One long-poll call to GET /updates. Returns (updates, next_marker)."""
    params: dict = {"timeout": timeout, "limit": limit}
    if marker is not None:
        params["marker"] = marker
    # A little slack over the server-side long-poll timeout so the HTTP client
    # doesn't cut the connection before MAX itself would time out the poll.
    with httpx.Client(base_url=base_url, timeout=timeout + 10) as client:
        response = client.get("/updates", params=params, headers=_headers(token))
    if response.status_code != 200:
        raise MaxApiError(f"GET /updates -> {response.status_code}: {response.text[:500]}")
    data = response.json()
    return data.get("updates", []), data.get("marker")


def send_message(base_url: str, token: str, chat_id: str, text: str, buttons: list[list[dict]] | None = None) -> dict:
    """POST /messages - plain text, optionally with an inline_keyboard attachment
    (buttons: rows of {"type": "callback", "text": ..., "payload": ...})."""
    payload: dict = {"text": text, "chat_id": chat_id}
    if buttons:
        payload["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
    with httpx.Client(base_url=base_url, timeout=15) as client:
        response = client.post("/messages", json=payload, headers=_headers(token))
    if response.status_code not in (200, 201):
        raise MaxApiError(f"POST /messages -> {response.status_code}: {response.text[:500]}")
    return response.json()
