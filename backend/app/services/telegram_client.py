"""Thin HTTP client over the Telegram Bot API (https://core.telegram.org/bots/api).

Unlike max_client.py, this one is written against a stable, extensively
documented, officially-maintained API - verified against a real bot token
(docs/decisions.md) rather than transcribed blind, but with far fewer
surprises expected: chat_id genuinely is a JSON body field (getUpdates/
sendMessage), reply-to-message is a flat integer (reply_to_message_id), and
the server's TLS certificate chains to a standard public CA - no special
trust-store handling needed the way MAX's Russian state CA required.
"""

import httpx

DEFAULT_BASE_URL = "https://api.telegram.org"


class TelegramApiError(RuntimeError):
    pass


def _url(base_url: str, token: str, method: str) -> str:
    return f"{base_url}/bot{token}/{method}"


def _check(response: httpx.Response, method: str) -> dict:
    if response.status_code != 200:
        raise TelegramApiError(f"{method} -> {response.status_code}: {response.text[:500]}")
    data = response.json()
    if not data.get("ok"):
        raise TelegramApiError(f"{method} -> {data}")
    return data


def get_updates(base_url: str, token: str, offset: int | None, timeout: int = 20, limit: int = 100) -> list[dict]:
    """One long-poll call to getUpdates. `offset` is the last seen update_id +
    1 (Telegram's own ack-by-offset scheme - acks everything below it)."""
    params: dict = {"timeout": timeout, "limit": limit}
    if offset is not None:
        params["offset"] = offset
    with httpx.Client(timeout=timeout + 10) as client:
        response = client.get(_url(base_url, token, "getUpdates"), params=params)
    return _check(response, "getUpdates")["result"]


def send_message(
    base_url: str,
    token: str,
    chat_id: str,
    text: str,
    buttons: list[list[dict]] | None = None,
    reply_to_message_id: int | None = None,
) -> dict:
    """POST sendMessage - chat_id is a genuine JSON body field here (verified
    live). `buttons`: rows of {"text": ..., "payload": ...} in the same
    generic shape telegram_channel.py shares with max_channel.py, translated
    here into Telegram's own inline_keyboard callback_data field name."""
    payload: dict = {"chat_id": chat_id, "text": text}
    if buttons:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": b["text"], "callback_data": b["payload"]} for b in row] for row in buttons]
        }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    with httpx.Client(timeout=15) as client:
        response = client.post(_url(base_url, token, "sendMessage"), json=payload)
    return _check(response, "sendMessage")["result"]


def answer_callback_query(base_url: str, token: str, callback_query_id: str) -> None:
    """Telegram clients show a loading spinner on a tapped inline button
    until this is called - purely cosmetic (no functional effect if
    skipped), but cheap to always do."""
    with httpx.Client(timeout=15) as client:
        response = client.post(
            _url(base_url, token, "answerCallbackQuery"), json={"callback_query_id": callback_query_id}
        )
    _check(response, "answerCallbackQuery")


def set_commands(base_url: str, token: str, commands: list[dict]) -> dict:
    """POST setMyCommands - {"commands": [{"command": "start", "description":
    ...}]}. Unlike MAX's /me/commands, this is Telegram's own long-standing
    feature and reliably renders as the "/" command menu in the client."""
    with httpx.Client(timeout=15) as client:
        response = client.post(_url(base_url, token, "setMyCommands"), json={"commands": commands})
    return _check(response, "setMyCommands")


def get_file_path(base_url: str, token: str, file_id: str) -> str | None:
    """getFile resolves a file_id to a download path - Telegram attachments
    arrive as an opaque id, not a direct URL (unlike MAX's occasional direct
    `url`), so this extra hop is required before downloading."""
    with httpx.Client(timeout=15) as client:
        response = client.get(_url(base_url, token, "getFile"), params={"file_id": file_id})
    data = _check(response, "getFile")
    return data["result"].get("file_path")


def download_file(base_url: str, token: str, file_path: str) -> bytes:
    with httpx.Client(timeout=30) as client:
        from app.services.attachments import download_limited
        return download_limited(client, f"{base_url}/file/bot{token}/{file_path}")


def send_document(base_url: str, token: str, chat_id: str, filename: str, content: bytes, mime_type: str) -> dict:
    """Upload a private file directly; no publicly accessible attachment URL."""
    with httpx.Client(timeout=60) as client:
        response = client.post(_url(base_url, token, "sendDocument"), data={"chat_id": chat_id},
                               files={"document": (filename, content, mime_type)})
    return _check(response, "sendDocument")["result"]
