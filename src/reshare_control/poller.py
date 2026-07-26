"""One-cycle poll orchestration for detection."""

from datetime import datetime, timedelta, timezone
import json

from .enforce import reinstate_account, stop_account
from .notify import TelegramNotifier, should_notify
from .parse import NO_READING, normalize_userstats_body
from .state import UserStrikeState
from .strike import evaluate_strike
from .webif import CurlFetcher, OK


class CycleUserResult(object):
    def __init__(self, name, ecm_per_min, state, should_stop=False,
                 threshold=None, action="global", notified=False,
                 connected=None):
        self.name = name
        self.ecm_per_min = ecm_per_min
        self.state = state
        self.should_stop = bool(should_stop)
        self.threshold = threshold
        self.action = action
        self.notified = bool(notified)
        self.connected = connected

    def to_dict(self):
        return {
            "name": self.name,
            "ecm_per_min": None if self.ecm_per_min is NO_READING else self.ecm_per_min,
            "ecm_per_min_is_no_reading": self.ecm_per_min is NO_READING,
            "status": self.state.status,
            "strikes": self.state.consecutive_strikes,
            "should_stop": self.should_stop,
            "threshold": self.threshold,
            "action": self.action,
            "notified": self.notified,
            "connected": self.connected,
            "stopped_until": self.state.stopped_until,
        }


class CycleResult(object):
    def __init__(self, users=None, stopped_users=None, fetch_status=None):
        self.users = list(users or [])
        self.stopped_users = list(stopped_users or [])
        self.fetch_status = fetch_status

    def to_dict(self):
        return {
            "fetch_status": self.fetch_status,
            "stopped_users": list(self.stopped_users),
            "users": [user.to_dict() for user in self.users],
        }


def run_cycle(config, store, fetcher=None, evaluated_at=None, dry_run=False,
              notifier=None):
    fetcher = fetcher or CurlFetcher(config.base_url(), auth=config.auth(),
                                     timeout_s=config.request_timeout_s)
    fetch = fetcher.get("/oscamapi.json?part=userstats")
    if fetch.status == OK:
        monitored_users = normalize_userstats_body(fetch.body)
        if _needs_userconfig_retry(fetch.body, monitored_users):
            html_fetch = fetcher.get("/userconfig.html")
            if html_fetch.status == OK:
                monitored_users = normalize_userstats_body(
                    fetch.body,
                    userconfig_html=html_fetch.body,
                )
    else:
        monitored_users = None

    result_holder = {}
    notifier = notifier if notifier is not None else TelegramNotifier()

    def update(state):
        users = []
        stopped_users = []
        _reenable_expired_stops(config, store, state, fetcher, evaluated_at, dry_run)
        if fetch.status != OK:
            for name, current in sorted(state.users.items()):
                if current.status == "stopped":
                    continue
                current.exempt = name in config.exempt_users
                effective = _effective_config(config, name)
                evaluation = evaluate_strike(
                    NO_READING,
                    current,
                    effective,
                    evaluated_at=evaluated_at,
                )
                evaluation.state.exempt = effective.policy.action == "ignore"
                state.set_user(name, evaluation.state)
                users.append(CycleUserResult(name, NO_READING, evaluation.state,
                                             evaluation.should_stop,
                                             threshold=effective.max_ecm_per_min,
                                             action=effective.policy.action))
            result_holder["result"] = CycleResult(users, stopped_users, fetch.status)
            return state

        seen = set()
        for monitored in monitored_users:
            seen.add(monitored.name)
            current = state.get_user(monitored.name)
            if current is not None and current.status == "stopped":
                continue
            if current is None:
                current = UserStrikeState()
            current.last_connected = monitored.connected
            effective = _effective_config(config, monitored.name)
            before_strikes = current.consecutive_strikes
            current.exempt = effective.policy.action == "ignore"
            evaluation = evaluate_strike(
                monitored.ecm_per_min,
                current,
                effective,
                evaluated_at=evaluated_at,
                already_disabled=False,
            )
            evaluation.state.exempt = effective.policy.action == "ignore"
            stopped = False
            if evaluation.should_stop and not dry_run:
                stopped_until = _stopped_until(effective, evaluated_at)
                stop_account(
                    config,
                    store.config_dir,
                    monitored.name,
                    evaluation.state,
                    monitored.ecm_per_min,
                    fetcher=fetcher,
                    timestamp=evaluated_at,
                    stopped_until=stopped_until,
                )
                stopped_users.append(monitored.name)
                stopped = True
            crossed_threshold = (
                evaluation.state.consecutive_strikes >= effective.strike_count
                and before_strikes < effective.strike_count
            )
            notified = False
            if (not dry_run and monitored.ecm_per_min is not NO_READING
                    and should_notify(config, effective.policy, crossed_threshold, stopped)):
                notified = notifier.send(
                    config,
                    monitored.name,
                    monitored.ecm_per_min,
                    effective.max_ecm_per_min,
                    effective.policy.action,
                    stopped,
                ).ok
            state.set_user(monitored.name, evaluation.state)
            users.append(CycleUserResult(monitored.name, monitored.ecm_per_min,
                                         evaluation.state,
                                         evaluation.should_stop,
                                         threshold=effective.max_ecm_per_min,
                                         action=effective.policy.action,
                                         notified=notified,
                                         connected=monitored.connected))

        for name, current in sorted(state.users.items()):
            if name in seen or current.status == "stopped":
                continue
            effective = _effective_config(config, name)
            current.last_connected = False
            current.exempt = effective.policy.action == "ignore"
            evaluation = evaluate_strike(
                NO_READING,
                current,
                effective,
                evaluated_at=evaluated_at,
            )
            evaluation.state.exempt = effective.policy.action == "ignore"
            state.set_user(name, evaluation.state)
            users.append(CycleUserResult(name, NO_READING, evaluation.state,
                                         evaluation.should_stop,
                                         threshold=effective.max_ecm_per_min,
                                         action=effective.policy.action))

        result_holder["result"] = CycleResult(users, stopped_users, fetch.status)
        return state

    if dry_run:
        state = store.load()
        update(state)
    else:
        store.locked_update(update)
    return result_holder["result"]


class _EffectiveConfig(object):
    def __init__(self, config, username):
        self._config = config
        self.policy = config.policy_for(username)
        self.max_ecm_per_min = (
            self.policy.max_ecm_per_min
            if self.policy.max_ecm_per_min is not None
            else config.max_ecm_per_min
        )
        self.strike_count = config.strike_count
        self.stop_duration_min = (
            self.policy.stop_duration_min
            if self.policy.stop_duration_min is not None
            else config.stop_duration_min
        )
        self.auto_stop_enabled = _effective_auto_stop(config, self.policy)

    def __getattr__(self, name):
        return getattr(self._config, name)


def _effective_config(config, username):
    return _EffectiveConfig(config, username)


def _effective_auto_stop(config, policy):
    if policy.action == "ignore":
        return False
    if policy.action == "notify":
        return False
    if policy.action == "stop":
        return True
    return config.auto_stop_enabled


def _stopped_until(config, evaluated_at):
    if not config.stop_duration_min:
        return None
    return (_parse_time(evaluated_at) + timedelta(minutes=config.stop_duration_min)).isoformat().replace("+00:00", "Z")


def _reenable_expired_stops(config, store, state, fetcher, evaluated_at, dry_run):
    now = _parse_time(evaluated_at)
    for username, user_state in list(state.users.items()):
        if user_state.status != "stopped" or not user_state.stopped_until:
            continue
        if _parse_time(user_state.stopped_until) > now:
            continue
        if dry_run:
            user_state.status = "ok"
            user_state.consecutive_strikes = 0
            user_state.stopped_until = None
            state.set_user(username, user_state)
            continue
        state.set_user(username, reinstate_account(
            config,
            store.config_dir,
            username,
            user_state,
            fetcher=fetcher,
            timestamp=_format_time(now),
        ))


def _parse_time(value):
    if value:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    return datetime.now(timezone.utc).replace(microsecond=0)


def _format_time(value):
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _needs_userconfig_retry(body, users):
    try:
        data = json.loads(body or "")
    except (TypeError, ValueError):
        return False
    entries = _raw_entries(data)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("user"), dict):
            entry = entry.get("user")
        if entry.get("usermd5") and not (entry.get("name") or entry.get("username")):
            return True
    return bool(not users and "usermd5" in (body or ""))


def _raw_entries(data):
    if not isinstance(data, dict):
        return []
    oscam = data.get("oscam", data)
    if not isinstance(oscam, dict):
        return []
    candidates = []
    userstats = oscam.get("userstats")
    if isinstance(userstats, dict) and "user" in userstats:
        candidates.append(userstats.get("user"))
    if "users" in oscam:
        candidates.append(oscam.get("users"))
    status = oscam.get("status")
    if isinstance(status, dict) and "client" in status:
        candidates.append(status.get("client"))
    for key in ("user", "client"):
        if key in oscam:
            candidates.append(oscam.get(key))
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
        if isinstance(candidate, dict):
            return [candidate]
    return []
