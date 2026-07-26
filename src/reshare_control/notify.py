"""Notification delivery helpers."""

from __future__ import print_function

import json
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
        url = "https://api.telegram.org/bot%s/sendMessage" % config.telegram_bot_token
        payload = urlencode({
            "chat_id": config.telegram_chat_id,
            "text": text,
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
    state = "STOPPED" if stopped else "FLAGGED"
    return "\n".join([
        "OSCAM Reshare Control: %s" % state,
        "OSCam: %s" % config.name,
        "User: %s" % user,
        "Observed ECM/min: %s" % observed_ecm_min,
        "Limit ECM/min: %s" % threshold,
        "Action: %s" % action,
    ])
