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

import os

import httpx

DEFAULT_BASE_URL = "https://platform-api2.max.ru"

# platform-api2.max.ru's certificate chains to the Russian state CA
# (Минцифры) - installed into the OS trust store at image build time
# (Dockerfile: certs/russian-trusted-root-ca.pem + update-ca-certificates).
# httpx does NOT use the OS store by default - it bundles its own copy of
# certifi's Mozilla list and verifies against that instead - so it has to be
# pointed at the OS bundle explicitly or every call here fails with
# "unable to get local issuer certificate" even though the cert is trusted.
# Falls back to httpx's default (certifi) outside this Docker image, e.g. a
# bare local dev run.
_SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
VERIFY = _SYSTEM_CA_BUNDLE if os.path.exists(_SYSTEM_CA_BUNDLE) else True


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
    with httpx.Client(base_url=base_url, timeout=timeout + 10, verify=VERIFY) as client:
        response = client.get("/updates", params=params, headers=_headers(token))
    if response.status_code != 200:
        raise MaxApiError(f"GET /updates -> {response.status_code}: {response.text[:500]}")
    data = response.json()
    return data.get("updates", []), data.get("marker")


def send_message(
    base_url: str,
    token: str,
    chat_id: str,
    text: str,
    buttons: list[list[dict]] | None = None,
    reply_to_mid: str | None = None,
    attachments: list[dict] | None = None,
) -> dict:
    """POST /messages?chat_id=... - the recipient is a query parameter, not a
    body field (verified against a live bot: putting chat_id in the JSON body
    - as the public docs suggested - gets a 200-looking-shaped but actually
    400 "Unknown recipient" every time). Body carries only the content: text,
    optionally an inline_keyboard attachment (buttons: rows of
    {"type": "callback", "text": ..., "payload": ...}), optionally a `link`
    marking this message as a native reply to an earlier one (reply_to_mid).
    The exact `link` shape isn't in the public NewMessageBody docs beyond
    "object NewMessageLink" with no field list - docs/decisions.md records
    what was verified live; correcting it is a one-line change here."""
    payload: dict = {"text": text}
    if attachments:
        payload["attachments"] = list(attachments)
    if buttons:
        payload.setdefault("attachments", []).append({"type": "inline_keyboard", "payload": {"buttons": buttons}})
    if reply_to_mid:
        payload["link"] = {"type": "reply", "mid": reply_to_mid}
    with httpx.Client(base_url=base_url, timeout=15, verify=VERIFY) as client:
        response = client.post("/messages", params={"chat_id": chat_id}, json=payload, headers=_headers(token))
    if response.status_code not in (200, 201):
        raise MaxApiError(f"POST /messages -> {response.status_code}: {response.text[:500]}")
    return response.json()


def set_commands(base_url: str, token: str, commands: list[dict]) -> dict:
    """PATCH /me/commands - registers the bot's persistent command list (shown
    by MAX clients near the input field, independent of scroll position -
    unlike inline_keyboard buttons, which are attached to one message and
    scroll away with it). Body: {"commands": [{"name": ..., "description":
    ...}]}, max 32 entries, full replace each call."""
    with httpx.Client(base_url=base_url, timeout=15, verify=VERIFY) as client:
        response = client.patch("/me/commands", json={"commands": commands}, headers=_headers(token))
    if response.status_code not in (200, 201):
        raise MaxApiError(f"PATCH /me/commands -> {response.status_code}: {response.text[:500]}")
    return response.json()


def upload_file(base_url: str, token: str, filename: str, content: bytes, mime_type: str) -> str:
    with httpx.Client(base_url=base_url, timeout=60, verify=VERIFY) as client:
        response = client.post("/uploads", params={"type": "file"}, headers=_headers(token))
        if response.status_code not in (200, 201):
            raise MaxApiError(f"POST /uploads -> {response.status_code}")
        url = response.json().get("url")
        if not url or not url.startswith(("https://", "http://")):
            raise MaxApiError("Upload URL is missing")
        # The signed upload URL is supplied by MAX. Do not forward the bot
        # credential to a different host; multipart upload uses the signed URL.
        uploaded = client.post(url, files={"data": (filename, content, mime_type)})
        if uploaded.status_code not in (200, 201):
            raise MaxApiError(f"Upload -> {uploaded.status_code}")
        data = uploaded.json()
        result = data.get("token")
        if not result:
            raise MaxApiError("Upload response has no file token")
        return result
