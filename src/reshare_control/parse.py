"""Shared parser-side types and constants."""

import hashlib
from html.parser import HTMLParser
import json


class _NoReading(object):
    def __repr__(self):
        return "NO_READING"

    def __str__(self):
        return "NO_READING"

    def __bool__(self):
        return False

    __nonzero__ = __bool__


NO_READING = _NoReading()


class MonitoredUser(object):
    """Normalized user statistics record shared by parser, poller, and strike code."""

    def __init__(self, name, usermd5=None, disabled=False,
                 ecm_per_min=NO_READING, connected=None, raw_webif_stats=None):
        self.name = name
        self.usermd5 = usermd5
        self.disabled = bool(disabled)
        self.ecm_per_min = ecm_per_min
        self.connected = connected
        self.raw_webif_stats = dict(raw_webif_stats or {})

    def to_dict(self):
        value = None if self.ecm_per_min is NO_READING else self.ecm_per_min
        return {
            "name": self.name,
            "usermd5": self.usermd5,
            "disabled": self.disabled,
            "ecm_per_min": value,
            "ecm_per_min_is_no_reading": self.ecm_per_min is NO_READING,
            "connected": self.connected,
            "raw_webif_stats": dict(self.raw_webif_stats),
        }


def to_number_or_no_reading(value):
    if value is NO_READING or value is None:
        return NO_READING
    if isinstance(value, bool):
        return NO_READING
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return NO_READING
        try:
            number = float(text)
        except ValueError:
            return NO_READING
        if number.is_integer():
            return int(number)
        return number
    return NO_READING


class UserstatsValidation(object):
    """Minimal userstats validation result for install/test.

    This intentionally handles only the US1 validation shapes. The full tolerant
    WebIF normalizer, including all documented status/html/md5 joins, belongs to
    US2 tasks T025/T026.
    """

    def __init__(self, user_count=0, active_user_count=0, usable_ecm_count=0):
        self.user_count = user_count
        self.active_user_count = active_user_count
        self.usable_ecm_count = usable_ecm_count

    @property
    def has_users(self):
        return self.user_count > 0

    @property
    def has_usable_active_ecm(self):
        return self.usable_ecm_count > 0

    def to_dict(self):
        return {
            "user_count": self.user_count,
            "active_user_count": self.active_user_count,
            "usable_ecm_count": self.usable_ecm_count,
            "has_users": self.has_users,
            "has_usable_active_ecm": self.has_usable_active_ecm,
        }


def validate_userstats_body(body):
    """Return whether a userstats JSON body has usable active ECM/min stats."""
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return UserstatsValidation()
    users = _minimal_userstats_entries(data)
    result = UserstatsValidation(user_count=len(users))
    for user in users:
        if not isinstance(user, dict):
            continue
        if _is_disabled(user):
            continue
        result.active_user_count += 1
        if to_number_or_no_reading(user.get("total_ecm_min")) is not NO_READING:
            result.usable_ecm_count += 1
    return result


def normalize_userstats_body(body, userconfig_html=None):
    """Normalize OSCAM userstats JSON into active MonitoredUser records."""
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return []
    username_by_md5 = {}
    if userconfig_html:
        username_by_md5 = _usernames_by_md5(userconfig_html)
    users = []
    for entry in _all_userstats_entries(data):
        if not isinstance(entry, dict):
            continue
        if _is_disabled(entry):
            continue
        usermd5 = _string_or_none(entry.get("usermd5"))
        name = _string_or_none(entry.get("name")) or _string_or_none(entry.get("username"))
        if not name and usermd5:
            name = username_by_md5.get(usermd5.lower())
        if not name:
            continue
        users.append(MonitoredUser(
            name=name,
            usermd5=usermd5,
            disabled=False,
            ecm_per_min=_ecm_per_min(entry),
            connected=_connected(entry),
            raw_webif_stats=_scalar_fields(entry),
        ))
    return users


def _minimal_userstats_entries(data):
    if not isinstance(data, dict):
        return []
    oscam = data.get("oscam", data)
    if not isinstance(oscam, dict):
        return []
    candidates = []
    userstats = oscam.get("userstats")
    if isinstance(userstats, dict) and "user" in userstats:
        candidates.append(userstats.get("user"))
    for key in ("users", "user"):
        if key in oscam:
            candidates.append(oscam.get(key))
    for candidate in candidates:
        entries = _as_list(candidate)
        if entries:
            return [_unwrap_user_entry(entry) for entry in entries]
    return []


def _all_userstats_entries(data):
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
        entries = _as_list(candidate)
        if entries:
            return [_unwrap_user_entry(entry) for entry in entries]
    return []


def _as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _unwrap_user_entry(entry):
    if isinstance(entry, dict) and isinstance(entry.get("user"), dict):
        return entry.get("user")
    return entry


def _is_disabled(user):
    classname = _string_or_none(user.get("classname"))
    if classname and "disabled" in classname.lower():
        return True
    status = _string_or_none(user.get("status"))
    if status and "disabled" in status.lower():
        return True
    value = user.get("disabled")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


def _ecm_per_min(entry):
    for key in ("total_ecm_min", "ecm_per_min", "n_requ_m"):
        value = to_number_or_no_reading(entry.get(key))
        if value is not NO_READING:
            return value
    stats = entry.get("stats")
    if isinstance(stats, dict):
        for key in ("n_requ_m", "total_ecm_min", "ecm_per_min", "cwrate"):
            value = to_number_or_no_reading(stats.get(key))
            if value is not NO_READING:
                return value
    return NO_READING


def _connected(entry):
    status = _string_or_none(entry.get("status"))
    if status:
        text = status.lower()
        if "online" in text or "connected" in text:
            return True
        if "offline" in text or "disconnected" in text:
            return False
    classname = _string_or_none(entry.get("classname"))
    if classname:
        text = classname.lower()
        if "online" in text or "connected" in text:
            return True
        if "offline" in text or "disabled" in text:
            return False
    connection = entry.get("connection")
    if isinstance(connection, dict):
        value = _string_or_none(connection.get("status") or connection.get("$"))
        if value:
            text = value.lower()
            if "connected" in text or text == "ok":
                return True
            if "error" in text or "disconnected" in text:
                return False
    return None


def _string_or_none(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _scalar_fields(entry):
    result = {}
    for key, value in entry.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
    return result


def _usernames_by_md5(html):
    parser = _UserConfigNameParser()
    try:
        parser.feed(html or "")
    except Exception:
        return {}
    result = {}
    for username in parser.usernames:
        digest = hashlib.md5(username.encode()).hexdigest()
        result[digest] = username
        result["id_" + digest] = username
    return result


class _UserConfigNameParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.usernames = []
        self._in_user_cell = False
        self._current_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if tag.lower() == "td" and "usercol1" in classes:
            self._in_user_cell = True
            self._current_parts = []
            value = _string_or_none(attrs.get("data-sort-value"))
            if value:
                self.usernames.append(value)

    def handle_data(self, data):
        if self._in_user_cell:
            self._current_parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "td" and self._in_user_cell:
            text = _string_or_none("".join(self._current_parts))
            if text and text not in self.usernames:
                self.usernames.append(text)
            self._in_user_cell = False
            self._current_parts = []
