"""Small standard-library web UI for managing local OSCam instances."""

from __future__ import print_function

import base64
import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import (
    AppConfig,
    ConfigError,
    InstanceConfig,
    UserPolicy,
    instance_state_dir,
    load_app_config,
    sanitize_instance_id,
    save_app_config,
    verify_password,
)
from .enforce import EnforcementError, enable_account, list_account_users, stop_account
from .notify import TelegramNotifier
from .poller import run_cycle
from .state import StateStore, UserStrikeState
from .webif import AUTH_FAILED, OK, OTHER_HTTP, TRANSPORT_ERROR, CurlFetcher


def serve(config_dir, bind_host=None, port=None):
    app = load_app_config(config_dir)
    host = bind_host or app.web.bind_host
    listen_port = int(port or app.web.port)

    class Handler(ReshareControlHandler):
        app_config_dir = config_dir

    server = ThreadingHTTPServer((host, listen_port), Handler)
    print("reshare-control web listening on http://%s:%s" % (host, listen_port))
    server.serve_forever()


class ReshareControlHandler(BaseHTTPRequestHandler):
    app_config_dir = "/etc/reshare-control"

    def do_GET(self):
        if not self._authorized():
            return self._require_auth()
        parsed = urlparse(self.path)
        if parsed.path in ("", "/"):
            return self._render_index()
        if parsed.path.startswith("/instance/"):
            return self._render_instance(parsed.path.rsplit("/", 1)[-1], parsed.query)
        self._send_html("Not found", status=404)

    def do_POST(self):
        if not self._authorized():
            return self._require_auth()
        parsed = urlparse(self.path)
        form = self._read_form()
        try:
            if parsed.path == "/instances/save":
                self._save_instance(form)
                return self._redirect("/")
            if parsed.path == "/instances/delete":
                self._delete_instance(form)
                return self._redirect("/")
            if parsed.path == "/instances/run":
                return self._run_instance(form)
            if parsed.path == "/instances/test-telegram":
                return self._test_telegram(form)
            if parsed.path == "/users/disable":
                return self._disable_user(form)
            if parsed.path == "/users/enable":
                return self._enable_user(form)
            if parsed.path == "/users/reset":
                return self._reset_user(form)
            if parsed.path == "/users/exempt":
                return self._set_exempt(form, True)
            if parsed.path == "/users/unexempt":
                return self._set_exempt(form, False)
            if parsed.path == "/users/policy":
                return self._save_user_policy(form)
        except Exception as exc:
            return self._send_html(_page("Error", "<p class='error'>%s</p><p><a href='/'>Back</a></p>" % _e(exc)), status=500)
        self._send_html("Not found", status=404)

    def log_message(self, fmt, *args):
        return

    def _authorized(self):
        app = load_app_config(self.app_config_dir)
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
        except Exception:
            return False
        user, sep, password = decoded.partition(":")
        return (
            sep == ":"
            and user == app.web.admin_user
            and verify_password(password, app.web.admin_password_hash)
        )

    def _require_auth(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="OSCAM Reshare Control"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"authentication required\n")

    def _render_index(self):
        app = load_app_config(self.app_config_dir)
        rows = []
        for instance in app.instances:
            state = StateStore(instance_state_dir(self.app_config_dir, instance.id)).load()
            flagged = sum(1 for item in state.users.values() if item.status == "flagged")
            stopped = sum(1 for item in state.users.values() if item.status == "stopped")
            rows.append("""
            <tr>
              <td><a href="/instance/%s">%s</a><span>%s:%s</span></td>
              <td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>
              <td class="actions">
                <a class="button" href="/instance/%s">Edit</a>
                <form method="post" action="/instances/run"><input type="hidden" name="id" value="%s"><button>Sync now</button></form>
                <form method="post" action="/instances/test-telegram"><input type="hidden" name="id" value="%s"><button>Test Telegram</button></form>
                <form method="post" action="/instances/delete"><input type="hidden" name="id" value="%s"><button class="danger">Delete</button></form>
              </td>
            </tr>
            """ % (
                _e(instance.id), _e(instance.name), _e(instance.host), instance.port,
                instance.max_ecm_per_min, instance.strike_count,
                "on" if instance.auto_stop_enabled else "off",
                "on" if instance.telegram_enabled else "off",
                "%s / %s" % (flagged, stopped),
                _e(instance.id),
                _e(instance.id), _e(instance.id), _e(instance.id),
            ))
        body = """
        <section class="toolbar">
          <h1>OSCAM Reshare Control</h1>
          <p>Manage OSCam instances running on this VPS.</p>
        </section>
        <section>
          <h2>Instances</h2>
          <table>
            <thead><tr><th>Name</th><th>ECM/min</th><th>Strikes</th><th>Auto-stop</th><th>Telegram</th><th>Flagged / stopped</th><th></th></tr></thead>
            <tbody>%s</tbody>
          </table>
        </section>
        %s
        """ % ("".join(rows) or "<tr><td colspan='7'>No OSCam instances configured yet.</td></tr>",
               _instance_form())
        self._send_html(_page("OSCAM Reshare Control", body))

    def _render_instance(self, instance_id, query=""):
        app = load_app_config(self.app_config_dir)
        instance = app.get_instance(sanitize_instance_id(instance_id))
        store = StateStore(instance_state_dir(self.app_config_dir, instance.id))
        state = store.load()
        filters = parse_qs(query)
        connected_only = _first(filters, "connected") == "1"
        special_only = _first(filters, "special") == "1"
        search = _first(filters, "q")
        rows = []
        for username, user_state in sorted(state.users.items()):
            if connected_only and user_state.last_connected is not True:
                continue
            if special_only and not _has_special_policy(instance, username):
                continue
            if search and search.lower() not in username.lower():
                continue
            policy = instance.policy_for(username)
            max_value = "" if policy.max_ecm_per_min is None else policy.max_ecm_per_min
            rows.append("""
            <tr>
              <td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>
              <td>
                <form method="post" action="/users/policy" class="policy">
                  <input type="hidden" name="id" value="%s"><input type="hidden" name="user" value="%s">
                  <label>Max ECM/min<input name="max_ecm_per_min" type="number" step="0.1" min="0.1" placeholder="%s" value="%s"></label>
                  <label>Stop min<input name="stop_duration_min" type="number" min="0" placeholder="%s" value="%s"></label>
                  <select name="action">
                    %s
                  </select>
                  <button>Save policy</button>
                </form>
              </td>
              <td class="actions">
                <form method="post" action="/users/reset"><input type="hidden" name="id" value="%s"><input type="hidden" name="user" value="%s"><button>Reset flag</button></form>
                <form method="post" action="/users/disable"><input type="hidden" name="id" value="%s"><input type="hidden" name="user" value="%s"><button class="danger">Disable account</button></form>
                <form method="post" action="/users/enable"><input type="hidden" name="id" value="%s"><input type="hidden" name="user" value="%s"><button>Enable account</button></form>
              </td>
            </tr>
            """ % (
                _e(username),
                _e(user_state.last_observed_ecm_min if user_state.last_observed_ecm_min is not None else "NO_READING"),
                user_state.consecutive_strikes,
                _connected_label(user_state.last_connected),
                _e(user_state.status),
                _e(user_state.stopped_until or ""),
                _e(policy.action),
                _e(instance.id), _e(username), instance.max_ecm_per_min, _e(max_value),
                instance.stop_duration_min, _e(_policy_duration_value(policy)),
                _action_options(policy.action),
                _e(instance.id), _e(username),
                _e(instance.id), _e(username), _e(instance.id), _e(username),
            ))
        body = """
        <section class="toolbar">
          <div><a href="/">Back</a><h1>%s</h1><p>%s:%s · %s</p></div>
          %s
        </section>
        %s
        <section>
          <h2>Users</h2>
          <div class="filters">
            <a class="button %s" href="/instance/%s%s">All users</a>
            <a class="button %s" href="/instance/%s?connected=1%s">Connected only</a>
            <a class="button %s" href="/instance/%s?special=1%s">Special settings</a>
          </div>
          <form method="get" action="/instance/%s" class="search">
            %s
            <input name="q" value="%s" placeholder="Search user">
            <button>Search</button>
            <a class="button" href="/instance/%s">Clear</a>
          </form>
          <table>
            <thead><tr><th>User</th><th>Last ECM/min</th><th>Strikes</th><th>Connected</th><th>Status</th><th>Stopped until</th><th>Action</th><th>Policy</th><th></th></tr></thead>
            <tbody>%s</tbody>
          </table>
        </section>
        """ % (
            _e(instance.name), _e(instance.host), instance.port, _e(instance.base_path),
            _instance_toolbar(instance),
            _instance_form(instance),
            "active" if not connected_only and not special_only else "", _e(instance.id), _search_suffix(search),
            "active" if connected_only else "", _e(instance.id), _search_suffix(search, separator="&"),
            "active" if special_only else "", _e(instance.id), _search_suffix(search, separator="&"),
            _e(instance.id), _filter_hidden_inputs(connected_only, special_only),
            _e(search), _e(instance.id),
            "".join(rows) or "<tr><td colspan='9'>No users match this view. Run this instance once.</td></tr>",
        )
        self._send_html(_page(instance.name, body))

    def _save_instance(self, form):
        app = load_app_config(self.app_config_dir)
        name = _first(form, "name")
        instance_id = sanitize_instance_id(_first(form, "id") or name)
        existing = None
        try:
            existing = app.get_instance(instance_id)
        except ConfigError:
            existing = None
        webif_pass = _first(form, "webif_pass")
        telegram_bot_token = _first(form, "telegram_bot_token")
        if existing is not None:
            if not webif_pass:
                webif_pass = existing.webif_pass
            if not telegram_bot_token:
                telegram_bot_token = existing.telegram_bot_token
        instance = InstanceConfig(
            id=instance_id,
            name=name,
            host=_first(form, "host"),
            port=_first(form, "port"),
            webif_user=_first(form, "webif_user"),
            webif_pass=webif_pass,
            base_path=_first(form, "base_path") or "/usr/local/etc",
            max_ecm_per_min=_first(form, "max_ecm_per_min") or 20,
            strike_count=_first(form, "strike_count") or 3,
            auto_stop_enabled=_first(form, "auto_stop_enabled") == "1",
            stop_duration_min=_first(form, "stop_duration_min") or 0,
            notify_enabled=_first(form, "notify_enabled") == "1",
            telegram_enabled=_first(form, "telegram_enabled") == "1",
            telegram_bot_token=telegram_bot_token,
            telegram_chat_id=_first(form, "telegram_chat_id"),
            poll_interval_min=_first(form, "poll_interval_min") or 5,
            request_timeout_s=_first(form, "request_timeout_s") or 5,
            user_policies=_existing_policies(app, instance_id),
        )
        app.upsert_instance(instance)
        _sync_local_account_users(self.app_config_dir, instance)
        save_app_config(app, self.app_config_dir)

    def _delete_instance(self, form):
        app = load_app_config(self.app_config_dir)
        app.remove_instance(sanitize_instance_id(_first(form, "id")))
        save_app_config(app, self.app_config_dir)

    def _run_instance(self, form):
        app = load_app_config(self.app_config_dir)
        instance = app.get_instance(sanitize_instance_id(_first(form, "id")))
        result = run_cycle(instance, StateStore(instance_state_dir(self.app_config_dir, instance.id)))
        _ensure_policies_from_result(app, instance, result)
        _sync_local_account_users(self.app_config_dir, instance)
        save_app_config(app, self.app_config_dir)
        return self._send_html(_page("Run complete", """
        <p>Fetch status: %s</p>
        <p>Users read: %s</p>
        <p>Local accounts: %s</p>
        <p>Stopped users: %s</p>
        <p><a href="/instance/%s">Back to instance</a></p>
        """ % (
            _e(result.fetch_status),
            len(result.users),
            len(instance.user_policies),
            _e(", ".join(result.stopped_users) or "none"),
            _e(instance.id),
        )))

    def _test_telegram(self, form):
        app = load_app_config(self.app_config_dir)
        instance = app.get_instance(sanitize_instance_id(_first(form, "id")))
        result = TelegramNotifier().send_test(instance)
        if result.ok:
            message = "<p>Telegram test message sent for %s.</p>" % _e(instance.name)
        else:
            message = "<p class='error'>Telegram test failed: %s</p>" % _e(result.error)
        return self._send_html(_page("Telegram test", """
        %s
        <p><a href="/instance/%s">Back to instance</a></p>
        """ % (message, _e(instance.id))))

    def _disable_user(self, form):
        app = load_app_config(self.app_config_dir)
        instance = app.get_instance(sanitize_instance_id(_first(form, "id")))
        username = _first(form, "user")
        store = StateStore(instance_state_dir(self.app_config_dir, instance.id))
        with store.locked():
            state = store.load()
            user_state = state.get_user(username) or UserStrikeState()
            stop_account(instance, store.config_dir, username, user_state,
                         user_state.last_observed_ecm_min)
            state.set_user(username, user_state)
            store.save(state)
        return self._redirect("/instance/%s" % instance.id)

    def _enable_user(self, form):
        app = load_app_config(self.app_config_dir)
        instance = app.get_instance(sanitize_instance_id(_first(form, "id")))
        store = StateStore(instance_state_dir(self.app_config_dir, instance.id))
        enable_account(instance, store.config_dir, _first(form, "user"), store)
        return self._redirect("/instance/%s" % instance.id)

    def _reset_user(self, form):
        app = load_app_config(self.app_config_dir)
        instance = app.get_instance(sanitize_instance_id(_first(form, "id")))
        username = _first(form, "user")
        store = StateStore(instance_state_dir(self.app_config_dir, instance.id))
        with store.locked():
            state = store.load()
            current = state.get_user(username) or UserStrikeState()
            current.consecutive_strikes = 0
            current.status = "ok"
            current.stopped_until = None
            state.set_user(username, current)
            store.save(state)
        return self._redirect("/instance/%s" % instance.id)

    def _set_exempt(self, form, exempt):
        app = load_app_config(self.app_config_dir)
        instance = app.get_instance(sanitize_instance_id(_first(form, "id")))
        username = _first(form, "user")
        users = set(instance.exempt_users)
        if exempt:
            users.add(username)
        else:
            users.discard(username)
        instance.exempt_users = sorted(users)
        app.upsert_instance(instance)
        save_app_config(app, self.app_config_dir)
        return self._redirect("/instance/%s" % instance.id)

    def _save_user_policy(self, form):
        app = load_app_config(self.app_config_dir)
        instance = app.get_instance(sanitize_instance_id(_first(form, "id")))
        username = _first(form, "user")
        instance.user_policies[username] = UserPolicy(
            max_ecm_per_min=_first(form, "max_ecm_per_min"),
            action=_first(form, "action") or "global",
            stop_duration_min=_first(form, "stop_duration_min"),
        ).to_dict()
        if username in instance.exempt_users:
            instance.exempt_users = [item for item in instance.exempt_users if item != username]
        app.upsert_instance(instance)
        save_app_config(app, self.app_config_dir)
        return self._redirect("/instance/%s" % instance.id)

    def _read_form(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        data = self.rfile.read(length).decode("utf-8") if length else ""
        return parse_qs(data)

    def _send_html(self, body, status=200):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()


def _instance_form(instance=None):
    instance = instance or _EmptyInstance()
    return """
    <section>
      <h2>%s</h2>
      <form method="post" action="/instances/save" class="grid">
        <input type="hidden" name="id" value="%s">
        <label>Name<input name="name" required value="%s"></label>
        <label>WebIF host<input name="host" required value="%s"></label>
        <label>WebIF port<input name="port" type="number" min="1" max="65535" required value="%s"></label>
        <label>WebIF user<input name="webif_user" value="%s"></label>
        <label>WebIF password<input name="webif_pass" type="password" placeholder="%s" value=""></label>
        <label>OSCam config path<input name="base_path" required value="%s"></label>
        <label>Max ECM/min<input name="max_ecm_per_min" type="number" step="0.1" min="0.1" value="%s"></label>
        <label>Strike count<input name="strike_count" type="number" min="1" value="%s"></label>
        <label>Stop duration minutes<input name="stop_duration_min" type="number" min="0" value="%s"></label>
        <label>Poll minutes<input name="poll_interval_min" type="number" min="1" value="%s"></label>
        <label>Timeout seconds<input name="request_timeout_s" type="number" min="1" value="%s"></label>
        <label class="check"><input name="auto_stop_enabled" type="checkbox" value="1" %s> Auto-stop</label>
        <label class="check"><input name="notify_enabled" type="checkbox" value="1" %s> Notify</label>
        <label class="check"><input name="telegram_enabled" type="checkbox" value="1" %s> Telegram</label>
        <label>Telegram bot token<input name="telegram_bot_token" type="password" placeholder="%s" value=""></label>
        <label>Telegram admin chat ID<input name="telegram_chat_id" value="%s"></label>
        <button>Save OSCam</button>
      </form>
    </section>
    """ % (
        "Edit OSCam" if instance.id else "Add OSCam",
        _e(instance.id), _e(instance.name), _e(instance.host), instance.port,
        _e(instance.webif_user), _secret_placeholder(instance.webif_pass), _e(instance.base_path),
        instance.max_ecm_per_min, instance.strike_count, instance.stop_duration_min, instance.poll_interval_min,
        instance.request_timeout_s, "checked" if instance.auto_stop_enabled else "",
        "checked" if instance.notify_enabled else "",
        "checked" if instance.telegram_enabled else "",
        _secret_placeholder(instance.telegram_bot_token), _e(instance.telegram_chat_id),
    )


def _instance_toolbar(instance):
    return """
    <div class="actions">
      <form method="post" action="/instances/run"><input type="hidden" name="id" value="%s"><button>Sync now</button></form>
      <form method="post" action="/instances/test-telegram"><input type="hidden" name="id" value="%s"><button>Test Telegram</button></form>
    </div>
    """ % (_e(instance.id), _e(instance.id))


def _exempt_button(instance, username, exempt):
    action = "/users/unexempt" if exempt else "/users/exempt"
    label = "Unexempt" if exempt else "Exempt"
    return '<form method="post" action="%s"><input type="hidden" name="id" value="%s"><input type="hidden" name="user" value="%s"><button>%s</button></form>' % (
        action, _e(instance.id), _e(username), label)


def _action_options(selected):
    labels = [
        ("global", "Use global"),
        ("notify", "Notify only"),
        ("stop", "Stop"),
        ("ignore", "Ignore"),
    ]
    return "".join(
        '<option value="%s" %s>%s</option>' % (
            value,
            "selected" if value == selected else "",
            label,
        )
        for value, label in labels
    )


def _policy_duration_value(policy):
    return "" if policy.stop_duration_min is None else policy.stop_duration_min


def _connected_label(value):
    if value is True:
        return "connected"
    if value is False:
        return "disconnected"
    return "unknown"


def _has_special_policy(instance, username):
    policy = instance.policy_for(username)
    return (
        policy.action != "global"
        or policy.max_ecm_per_min is not None
        or policy.stop_duration_min is not None
    )


def _search_suffix(search, separator="?"):
    if not search:
        return ""
    from urllib.parse import quote_plus

    return "%sq=%s" % (separator, quote_plus(search))


def _filter_hidden_inputs(connected_only, special_only):
    fields = []
    if connected_only:
        fields.append('<input type="hidden" name="connected" value="1">')
    if special_only:
        fields.append('<input type="hidden" name="special" value="1">')
    return "".join(fields)


def _existing_policies(app, instance_id):
    try:
        return app.get_instance(instance_id).user_policies
    except ConfigError:
        return {}


def _ensure_policies_from_result(app, instance, result):
    for user in result.users:
        instance.ensure_user_policy(user.name)
    app.upsert_instance(instance)


def _sync_local_account_users(config_dir, instance):
    store = StateStore(instance_state_dir(config_dir, instance.id))
    try:
        users = list_account_users(instance.base_path)
    except EnforcementError:
        return []
    state = store.load()
    for username in users:
        instance.ensure_user_policy(username)
        if state.get_user(username) is None:
            state.set_user(username, UserStrikeState(last_connected=False))
    store.save(state)
    return users


class _EmptyInstance(object):
    id = ""
    name = ""
    host = "127.0.0.1"
    port = 8888
    webif_user = ""
    webif_pass = ""
    base_path = "/usr/local/etc"
    max_ecm_per_min = 20
    strike_count = 3
    stop_duration_min = 0
    poll_interval_min = 5
    request_timeout_s = 5
    auto_stop_enabled = False
    notify_enabled = True
    telegram_enabled = False
    telegram_bot_token = ""
    telegram_chat_id = ""
    exempt_users = []
    user_policies = {}


def _page(title, body):
    return """<!doctype html>
    <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>%s</title><style>
    body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#f7f8fa;color:#16181d}
    section{max-width:1180px;margin:0 auto;padding:22px} h1{margin:0 0 4px;font-size:30px} h2{font-size:19px}
    .toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;background:#fff;border-bottom:1px solid #dde1e7;max-width:none}
    table{width:100%%;border-collapse:collapse;background:#fff;border:1px solid #dde1e7} th,td{text-align:left;padding:10px;border-bottom:1px solid #e8ebef;vertical-align:top}
    td span{display:block;color:#667085;font-size:13px;margin-top:3px}.actions{display:flex;gap:6px;flex-wrap:wrap}
    form{margin:0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;background:#fff;border:1px solid #dde1e7;padding:16px}
    .policy{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.policy input{width:96px}.policy select{font:inherit;padding:9px;border:1px solid #b9c0cb;border-radius:6px}
    label{display:flex;flex-direction:column;font-size:13px;font-weight:650;gap:5px}.check{flex-direction:row;align-items:center;margin-top:22px}
    input,textarea{font:inherit;padding:9px;border:1px solid #b9c0cb;border-radius:6px}textarea{min-height:72px}.wide{grid-column:1/-1}
    button,.button{font:inherit;font-weight:700;padding:8px 12px;border:1px solid #9aa3af;border-radius:6px;background:#fff;cursor:pointer;display:inline-block}.button.active{background:#16181d;color:#fff}
    .danger{border-color:#c2410c;color:#9a3412}.filters{display:flex;gap:8px;margin:0 0 10px}
    a{color:#0f5fb8;text-decoration:none}.error{color:#b42318;background:#fff0f0;border:1px solid #f4b4b4;padding:12px}
    </style></head><body>%s</body></html>""" % (_e(title), body)


def _first(form, key):
    values = form.get(key, [""])
    return values[0].strip() if values else ""


def _split_lines(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _e(value):
    return html.escape(str(value), quote=True)


def _secret_placeholder(value):
    return "leave blank to keep existing" if value else ""
