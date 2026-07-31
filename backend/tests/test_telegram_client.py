"""Regression tests for the raw Telegram Bot API request shapes in
telegram_client.py, verified against a real bot token (docs/decisions.md).
No network is used - httpx.MockTransport intercepts the request."""

import json

import httpx
import pytest

from app.services import telegram_client

_RealClient = httpx.Client  # captured before any monkeypatching below


def _mock_client_factory(handler):
    def factory(**kwargs):
        return _RealClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory


@pytest.fixture()
def captured():
    return {}


def test_send_message_puts_chat_id_and_text_in_body(monkeypatch, captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1, "text": "ok"}})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    telegram_client.send_message("https://api.telegram.org", "test-token", "42", "Привет")

    assert captured["path"] == "/bottest-token/sendMessage"
    body = json.loads(captured["body"])
    assert body["chat_id"] == "42"
    assert body["text"] == "Привет"
    assert "reply_markup" not in body
    assert "reply_to_message_id" not in body


def test_send_message_with_buttons_builds_inline_keyboard(monkeypatch, captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 2}})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    buttons = [[{"type": "callback", "text": "OH-1", "payload": "ticket:1"}]]
    telegram_client.send_message("https://api.telegram.org", "test-token", "42", "Выберите", buttons=buttons)

    body = json.loads(captured["body"])
    assert body["reply_markup"] == {"inline_keyboard": [[{"text": "OH-1", "callback_data": "ticket:1"}]]}


def test_send_message_with_reply_sets_flat_reply_to_message_id(monkeypatch, captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 3}})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    telegram_client.send_message("https://api.telegram.org", "test-token", "42", "Ответ", reply_to_message_id=17)

    body = json.loads(captured["body"])
    assert body["reply_to_message_id"] == 17


def test_send_message_raises_on_ok_false(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": "Bad Request: chat not found"})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    with pytest.raises(telegram_client.TelegramApiError, match="chat not found"):
        telegram_client.send_message("https://api.telegram.org", "test-token", "1", "hi")


def test_send_message_raises_on_error_status(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    with pytest.raises(telegram_client.TelegramApiError):
        telegram_client.send_message("https://api.telegram.org", "test-token", "1", "hi")


def test_answer_callback_query_posts_id(monkeypatch, captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True, "result": True})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    telegram_client.answer_callback_query("https://api.telegram.org", "test-token", "cbq-123")

    assert captured["path"] == "/bottest-token/answerCallbackQuery"
    assert json.loads(captured["body"]) == {"callback_query_id": "cbq-123"}


def test_set_commands_posts_command_list(monkeypatch, captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True, "result": True})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    commands = [{"command": "start", "description": "Показать меню"}]
    telegram_client.set_commands("https://api.telegram.org", "test-token", commands)

    assert captured["path"] == "/bottest-token/setMyCommands"
    assert json.loads(captured["body"]) == {"commands": commands}


def test_get_updates_sends_offset_and_parses_result(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["offset"] == "6"
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 6, "message": {}}]})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    updates = telegram_client.get_updates("https://api.telegram.org", "test-token", offset=6)
    assert len(updates) == 1
    assert updates[0]["update_id"] == 6


def test_get_file_path_returns_result_path(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["file_id"] == "file-abc"
        return httpx.Response(200, json={"ok": True, "result": {"file_path": "documents/file.pdf"}})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    path = telegram_client.get_file_path("https://api.telegram.org", "test-token", "file-abc")
    assert path == "documents/file.pdf"
