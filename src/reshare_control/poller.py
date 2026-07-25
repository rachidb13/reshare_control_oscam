"""One-cycle poll orchestration for detection."""

import json

from .enforce import stop_account
from .parse import NO_READING, normalize_userstats_body
from .state import UserStrikeState
from .strike import evaluate_strike
from .webif import CurlFetcher, OK


class CycleUserResult(object):
    def __init__(self, name, ecm_per_min, state, should_stop=False):
        self.name = name
        self.ecm_per_min = ecm_per_min
        self.state = state
        self.should_stop = bool(should_stop)

    def to_dict(self):
        return {
            "name": self.name,
            "ecm_per_min": None if self.ecm_per_min is NO_READING else self.ecm_per_min,
            "ecm_per_min_is_no_reading": self.ecm_per_min is NO_READING,
            "status": self.state.status,
            "strikes": self.state.consecutive_strikes,
            "should_stop": self.should_stop,
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


def run_cycle(config, store, fetcher=None, evaluated_at=None, dry_run=False):
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

    def update(state):
        users = []
        stopped_users = []
        if fetch.status != OK:
            for name, current in sorted(state.users.items()):
                if current.status == "stopped":
                    continue
                current.exempt = name in config.exempt_users
                evaluation = evaluate_strike(
                    NO_READING,
                    current,
                    config,
                    evaluated_at=evaluated_at,
                )
                evaluation.state.exempt = name in config.exempt_users
                state.set_user(name, evaluation.state)
                users.append(CycleUserResult(name, NO_READING, evaluation.state,
                                             evaluation.should_stop))
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
            current.exempt = monitored.name in config.exempt_users
            evaluation = evaluate_strike(
                monitored.ecm_per_min,
                current,
                config,
                evaluated_at=evaluated_at,
                already_disabled=False,
            )
            evaluation.state.exempt = monitored.name in config.exempt_users
            if evaluation.should_stop and not dry_run:
                stop_account(
                    config,
                    store.config_dir,
                    monitored.name,
                    evaluation.state,
                    monitored.ecm_per_min,
                    fetcher=fetcher,
                    timestamp=evaluated_at,
                )
                stopped_users.append(monitored.name)
            state.set_user(monitored.name, evaluation.state)
            users.append(CycleUserResult(monitored.name, monitored.ecm_per_min,
                                         evaluation.state,
                                         evaluation.should_stop))

        for name, current in sorted(state.users.items()):
            if name in seen or current.status == "stopped":
                continue
            current.exempt = name in config.exempt_users
            evaluation = evaluate_strike(
                NO_READING,
                current,
                config,
                evaluated_at=evaluated_at,
            )
            evaluation.state.exempt = name in config.exempt_users
            state.set_user(name, evaluation.state)
            users.append(CycleUserResult(name, NO_READING, evaluation.state,
                                         evaluation.should_stop))

        result_holder["result"] = CycleResult(users, stopped_users, fetch.status)
        return state

    if dry_run:
        state = store.load()
        update(state)
    else:
        store.locked_update(update)
    return result_holder["result"]


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
