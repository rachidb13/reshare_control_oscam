"""Notification delivery helpers."""

from __future__ import print_function

import json
from html import escape
from urllib.parse import urlencode
from urllib.request import urlopen, Request


class NotificationResult(object):
    def __init__(self, ok, error=""):
        self.ok = bool(ok)
        self.error = error


class TelegramNotifier(object):
    def send(self, config, user, observed_ecm_min, threshold, action, stopped):
        if not _telegram_ready(config):
            return NotificationResult(False, "telegram disabled or incomplete")
        text = _message(config, user, observed_ecm_min, threshold, action, stopped)
        return self.send_text(config, text)

    def send_test(self, config):
        if not _telegram_ready(config):
            return NotificationResult(False, "telegram disabled or incomplete")
        return self.send_text(config, "\n".join([
            "🟦 <b>OSCAM Reshare Control</b>",
            "<b>Status:</b> TEST MESSAGE",
            "<b>OSCam:</b> %s" % _h(config.name),
            "<b>WebIF:</b> %s:%s" % (_h(config.host), _h(config.port)),
            "",
            "Telegram notifications are configured.",
        ]))

    def send_text(self, config, text):
        url = "https://api.telegram.org/bot%s/sendMessage" % config.telegram_bot_token
        payload = urlencode({
            "chat_id": config.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        request = Request(url, data=payload)
        try:
            response = urlopen(request, timeout=config.request_timeout_s)
            body = response.read().decode("utf-8", "replace")
            data = json.loads(body or "{}")
            if data.get("ok"):
                return NotificationResult(True)
            return NotificationResult(False, data.get("description", body))
        except Exception as exc:
            return NotificationResult(False, str(exc))


def should_notify(config, policy, crossed_threshold, stopped):
    if not config.notify_enabled and policy.action == "global":
        return False
    if policy.action == "ignore":
        return False
    if policy.action in ("notify", "stop"):
        return crossed_threshold or stopped
    return crossed_threshold or stopped


def _telegram_ready(config):
    return (
        getattr(config, "telegram_enabled", False)
        and bool(getattr(config, "telegram_bot_token", ""))
        and bool(getattr(config, "telegram_chat_id", ""))
    )


def _message(config, user, observed_ecm_min, threshold, action, stopped):
    icon = "🔴" if stopped else "🟠"
    state = "STOPPED" if stopped else "FLAGGED"
    action_label = "Stop user" if action == "stop" else "Notify only" if action == "notify" else action
    return "\n".join([
        "%s <b>OSCAM Reshare Control</b>" % icon,
        "<b>Status:</b> %s" % state,
        "",
        "<b>OSCam:</b> %s" % _h(config.name),
        "<b>User:</b> <code>%s</code>" % _h(user),
        "<b>Observed ECM/min:</b> <code>%s</code>" % _h(observed_ecm_min),
        "<b>Limit ECM/min:</b> <code>%s</code>" % _h(threshold),
        "<b>Action:</b> %s" % _h(action_label),
    ])


def _h(value):
    return escape(str(value), quote=False)
