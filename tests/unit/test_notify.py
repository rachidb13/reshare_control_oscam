from urllib.parse import parse_qs

from reshare_control.config import InstanceConfig
from reshare_control.notify import TelegramNotifier
from reshare_control.webapp import _instance_toolbar


class FakeResponse(object):
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body


def test_telegram_test_message_uses_saved_instance_settings(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = parse_qs(request.data.decode("utf-8"))
        return FakeResponse(b'{"ok": true}')

    monkeypatch.setattr("reshare_control.notify.urlopen", fake_urlopen)
    config = InstanceConfig(
        id="main",
        name="Main OSCam",
        host="127.0.0.1",
        port=1303,
        telegram_enabled=True,
        telegram_bot_token="123:abc",
        telegram_chat_id="42",
        request_timeout_s=7,
    )

    result = TelegramNotifier().send_test(config)

    assert result.ok is True
    assert captured["url"] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert captured["timeout"] == 7
    assert captured["payload"]["chat_id"] == ["42"]
    assert captured["payload"]["parse_mode"] == ["HTML"]
    assert "<b>OSCAM Reshare Control</b>" in captured["payload"]["text"][0]
    assert "<b>Status:</b> TEST MESSAGE" in captured["payload"]["text"][0]
    assert "Main OSCam" in captured["payload"]["text"][0]
    assert "127.0.0.1:1303" in captured["payload"]["text"][0]


def test_telegram_test_message_requires_complete_settings():
    config = InstanceConfig(id="main", name="Main", host="127.0.0.1", port=1303, telegram_enabled=True)

    result = TelegramNotifier().send_test(config)

    assert result.ok is False
    assert result.error == "telegram disabled or incomplete"


def test_instance_toolbar_has_telegram_test_button():
    config = InstanceConfig(id="main", name="Main", host="127.0.0.1", port=1303)

    html = _instance_toolbar(config)

    assert 'action="/instances/test-telegram"' in html
    assert 'name="id" value="main"' in html
    assert "Test Telegram" in html
