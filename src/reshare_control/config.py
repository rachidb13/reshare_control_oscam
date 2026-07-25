"""Configuration loading, validation, persistence, and safe log masking."""

import json
import logging
import os
import stat
import tempfile


DEFAULT_CONFIG_DIR = "/etc/reshare-control"
CONFIG_FILENAME = "config.json"

DEFAULTS = {
    "webif_user": "",
    "webif_pass": "",
    "base_path": "/usr/local/etc",
    "max_ecm_per_min": 20,
    "strike_count": 3,
    "auto_stop_enabled": False,
    "poll_interval_min": 5,
    "request_timeout_s": 5,
    "exempt_users": [],
}

SECRET_FIELDS = set(["webif_pass"])
USERNAME_FIELDS = set(["webif_user"])


class ConfigError(ValueError):
    """Raised when config.json is missing, malformed, or invalid."""


class InstanceConfig(object):
    """Validated OSCAM instance configuration."""

    def __init__(self, host, port, webif_user="", webif_pass="",
                 base_path="/usr/local/etc", max_ecm_per_min=20,
                 strike_count=3, auto_stop_enabled=False,
                 poll_interval_min=5, request_timeout_s=5,
                 exempt_users=None):
        self.host = host
        self.port = port
        self.webif_user = webif_user
        self.webif_pass = webif_pass
        self.base_path = base_path
        self.max_ecm_per_min = max_ecm_per_min
        self.strike_count = strike_count
        self.auto_stop_enabled = auto_stop_enabled
        self.poll_interval_min = poll_interval_min
        self.request_timeout_s = request_timeout_s
        self.exempt_users = list(exempt_users or [])
        self.validate()

    @classmethod
    def from_dict(cls, data):
        merged = dict(DEFAULTS)
        merged.update(data or {})
        missing = [key for key in ("host", "port") if key not in merged]
        if missing:
            raise ConfigError("missing required config key(s): %s" % ", ".join(missing))
        return cls(**merged)

    def to_dict(self):
        return {
            "host": self.host,
            "port": self.port,
            "webif_user": self.webif_user,
            "webif_pass": self.webif_pass,
            "base_path": self.base_path,
            "max_ecm_per_min": self.max_ecm_per_min,
            "strike_count": self.strike_count,
            "auto_stop_enabled": self.auto_stop_enabled,
            "poll_interval_min": self.poll_interval_min,
            "request_timeout_s": self.request_timeout_s,
            "exempt_users": list(self.exempt_users),
        }

    def validate(self):
        if not isinstance(self.host, str) or not self.host.strip():
            raise ConfigError("host must be a non-empty string")
        self.port = _integer("port", self.port)
        if self.port < 1 or self.port > 65535:
            raise ConfigError("port must be between 1 and 65535")
        if not isinstance(self.webif_user, str):
            raise ConfigError("webif_user must be a string")
        if not isinstance(self.webif_pass, str):
            raise ConfigError("webif_pass must be a string")
        if not isinstance(self.base_path, str) or not self.base_path:
            raise ConfigError("base_path must be a non-empty string")
        self.max_ecm_per_min = _number("max_ecm_per_min", self.max_ecm_per_min)
        if self.max_ecm_per_min <= 0:
            raise ConfigError("max_ecm_per_min must be greater than 0")
        self.strike_count = _integer("strike_count", self.strike_count)
        if self.strike_count < 1:
            raise ConfigError("strike_count must be at least 1")
        if not isinstance(self.auto_stop_enabled, bool):
            raise ConfigError("auto_stop_enabled must be a boolean")
        self.poll_interval_min = _integer("poll_interval_min", self.poll_interval_min)
        if self.poll_interval_min < 1:
            raise ConfigError("poll_interval_min must be at least 1")
        self.request_timeout_s = _integer("request_timeout_s", self.request_timeout_s)
        if self.request_timeout_s < 1:
            raise ConfigError("request_timeout_s must be at least 1")
        if not isinstance(self.exempt_users, list):
            raise ConfigError("exempt_users must be a list")
        for user in self.exempt_users:
            if not isinstance(user, str):
                raise ConfigError("exempt_users must contain strings only")

    def base_url(self):
        return "http://%s:%s" % (self.host, self.port)

    def auth(self):
        return (self.webif_user, self.webif_pass)


def config_path(config_dir):
    return os.path.join(config_dir, CONFIG_FILENAME)


def load_config(config_dir=DEFAULT_CONFIG_DIR, logger=None):
    path = config_path(config_dir)
    _ensure_owner_only_if_exists(path, logger)
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
    except IOError as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc))
    except ValueError as exc:
        raise ConfigError("invalid JSON in %s: %s" % (path, exc))
    return InstanceConfig.from_dict(data)


def save_config(config, config_dir=DEFAULT_CONFIG_DIR):
    if not isinstance(config, InstanceConfig):
        config = InstanceConfig.from_dict(config)
    _atomic_write_json(config_path(config_dir), config.to_dict())


def mask_username(username):
    if username is None:
        return ""
    text = str(username)
    if not text:
        return ""
    if len(text) == 1:
        return "*"
    if len(text) == 2:
        return text[0] + "*"
    return text[0] + ("*" * (len(text) - 2)) + text[-1]


def mask_for_log(value):
    """Return a JSON-safe copy with secrets removed and usernames masked."""
    if isinstance(value, InstanceConfig):
        value = value.to_dict()
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            if key in SECRET_FIELDS:
                masked[key] = "***"
            elif key in USERNAME_FIELDS:
                masked[key] = mask_username(item)
            elif key == "exempt_users" and isinstance(item, list):
                masked[key] = [mask_username(user) for user in item]
            else:
                masked[key] = mask_for_log(item)
        return masked
    if isinstance(value, list):
        return [mask_for_log(item) for item in value]
    return value


def _integer(name, value):
    if isinstance(value, bool):
        raise ConfigError("%s must be an integer" % name)
    try:
        converted = int(value)
    except (TypeError, ValueError):
        raise ConfigError("%s must be an integer" % name)
    if converted != value and not isinstance(value, str):
        raise ConfigError("%s must be an integer" % name)
    return converted


def _number(name, value):
    if isinstance(value, bool):
        raise ConfigError("%s must be a number" % name)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ConfigError("%s must be a number" % name)


def _ensure_owner_only_if_exists(path, logger=None):
    if not os.path.exists(path):
        return
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        log = logger or logging.getLogger(__name__)
        log.warning("config file permissions were too broad; resetting %s to 0600", path)
        os.chmod(path, 0o600)


def _atomic_write_json(path, data):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, 0o700)
    fd, tmp_path = tempfile.mkstemp(prefix=".config.", suffix=".tmp", dir=directory or ".")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_path, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
