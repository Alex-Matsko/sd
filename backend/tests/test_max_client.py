"""Regression tests for the raw MAX Bot API request shapes in max_client.py.

These pin down two things discovered by testing against a real bot token
(docs/decisions.md): `chat_id` must travel as a query parameter on
POST /messages, not a JSON body field - the public docs suggested the body,
which the real API silently rejects with 400 "Unknown recipient" (a
plausible-looking error, easy to not notice is about request shape rather
than an actually-unknown chat). No network is used - httpx.MockTransport
intercepts the request so we can assert on it directly."""

import json

import httpx
import pytest

from app.services import max_client

_RealClient = httpx.Client  # captured before any monkeypatching below


def _mock_client_factory(handler):
    def factory(**kwargs):
        kwargs.pop("verify", None)
        return _RealClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory


@pytest.fixture()
def captured():
    return {}


def test_send_message_puts_chat_id_in_query_params(monkeypatch, captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = request.url
        captured["body"] = request.content
        return httpx.Response(200, json={"message": {"body": {"text": "ok"}}})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    max_client.send_message("https://platform-api2.max.ru", "test-token", "28746558", "Привет")

    assert captured["url"].params["chat_id"] == "28746558"
    body = json.loads(captured["body"])
    assert "chat_id" not in body
    assert body["text"] == "Привет"


def test_send_message_with_buttons_still_omits_chat_id_from_body(monkeypatch, captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = request.url
        captured["body"] = request.content
        return httpx.Response(200, json={"message": {"body": {"text": "ok"}}})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    buttons = [[{"type": "callback", "text": "OH-1", "payload": "ticket:1"}]]
    max_client.send_message("https://platform-api2.max.ru", "test-token", "42", "Выберите", buttons=buttons)

    assert captured["url"].params["chat_id"] == "42"
    body = json.loads(captured["body"])
    assert "chat_id" not in body
    assert body["attachments"][0]["type"] == "inline_keyboard"


def test_send_message_raises_on_error_status(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "proto.payload", "message": "Unknown recipient"})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    with pytest.raises(max_client.MaxApiError, match="Unknown recipient"):
        max_client.send_message("https://platform-api2.max.ru", "test-token", "1", "hi")


def test_get_updates_sends_marker_and_parses_response(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["marker"] == "5"
        return httpx.Response(200, json={"updates": [{"update_type": "message_created"}], "marker": 6})

    monkeypatch.setattr(httpx, "Client", _mock_client_factory(handler))

    updates, marker = max_client.get_updates("https://platform-api2.max.ru", "test-token", marker=5)
    assert len(updates) == 1
    assert marker == 6
