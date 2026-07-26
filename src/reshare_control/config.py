"""Configuration loading, validation, persistence, and safe log masking."""

from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import os
import secrets
import stat
import tempfile


DEFAULT_CONFIG_DIR = "/etc/reshare-control"
CONFIG_FILENAME = "config.json"

DEFAULTS = {
    "id": "default",
    "name": "Default OSCam",
    "webif_user": "",
    "webif_pass": "",
    "base_path": "/usr/local/etc",
    "max_ecm_per_min": 20,
    "strike_count": 3,
    "auto_stop_enabled": False,
    "stop_duration_min": 0,
    "notify_enabled": True,
    "telegram_enabled": False,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "poll_interval_min": 5,
    "request_timeout_s": 5,
    "exempt_users": [],
    "user_policies": {},
}

WEB_DEFAULTS = {
    "bind_host": "0.0.0.0",
    "port": 8787,
    "admin_user": "admin",
    "admin_password_hash": "",
}

DEFAULT_WG_API_URL = "https://admin.kanasavpn.com/api/wg"
DEFAULT_OSCAM_CHECKER_BINARY_URL = "SET_RC_OSCAM_CHECKER_URL"

VPN_DEFAULTS = {
    "enabled": False,
    "license_key": "",
    "panel_fqdn": "",
    "agent_id": "",
    "wg_api_url": DEFAULT_WG_API_URL,
    "issue_key_url": "",
    "oscam_checker_binary_url": DEFAULT_OSCAM_CHECKER_BINARY_URL,
    "bootstrap_key": "",
    "server_key": "",
    "wg_port": None,
    "wg_subnet": "",
    "wg_listen_port": 51820,
    "status": "",
    "enrolled_at": "",
}

SECRET_FIELDS = set([
    "webif_pass",
    "admin_password_hash",
    "telegram_bot_token",
    "license_key",
    "bootstrap_key",
    "server_key",
])
USERNAME_FIELDS = set(["webif_user", "admin_user"])
USER_ACTIONS = set(["global", "notify", "stop", "ignore"])


class ConfigError(ValueError):
    """Raised when config.json is missing, malformed, or invalid."""


class InstanceConfig(object):
    """Validated OSCAM instance configuration."""

    def __init__(self, host, port, id="default", name="Default OSCam",
                 webif_user="", webif_pass="", base_path="/usr/local/etc",
                 max_ecm_per_min=20, strike_count=3,
                 auto_stop_enabled=False, stop_duration_min=0,
                 notify_enabled=True,
                 telegram_enabled=False, telegram_bot_token="",
                 telegram_chat_id="", poll_interval_min=5,
                 request_timeout_s=5, exempt_users=None,
                 user_policies=None):
        self.id = id
        self.name = name
        self.host = host
        self.port = port
        self.webif_user = webif_user
        self.webif_pass = webif_pass
        self.base_path = base_path
        self.max_ecm_per_min = max_ecm_per_min
        self.strike_count = strike_count
        self.auto_stop_enabled = auto_stop_enabled
        self.stop_duration_min = stop_duration_min
        self.notify_enabled = notify_enabled
        self.telegram_enabled = telegram_enabled
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.poll_interval_min = poll_interval_min
        self.request_timeout_s = request_timeout_s
        self.exempt_users = list(exempt_users or [])
        self.user_policies = dict(
            (str(name), UserPolicy.from_dict(policy).to_dict())
            for name, policy in (user_policies or {}).items()
        )
        self.validate()

    @classmethod
    def from_dict(cls, data):
        merged = dict(DEFAULTS)
        merged.update(data or {})
        missing = [key for key in ("host", "port") if key not in merged]
        if missing:
            raise ConfigError("missing required config key(s): %s" % ", ".join(missing))
        merged["id"] = sanitize_instance_id(merged.get("id") or merged.get("name"))
        return cls(**merged)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "webif_user": self.webif_user,
            "webif_pass": self.webif_pass,
            "base_path": self.base_path,
            "max_ecm_per_min": self.max_ecm_per_min,
            "strike_count": self.strike_count,
            "auto_stop_enabled": self.auto_stop_enabled,
            "stop_duration_min": self.stop_duration_min,
            "notify_enabled": self.notify_enabled,
            "telegram_enabled": self.telegram_enabled,
            "telegram_bot_token": self.telegram_bot_token,
            "telegram_chat_id": self.telegram_chat_id,
            "poll_interval_min": self.poll_interval_min,
            "request_timeout_s": self.request_timeout_s,
            "exempt_users": list(self.exempt_users),
            "user_policies": dict(self.user_policies),
        }

    def validate(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise ConfigError("id must be a non-empty string")
        if self.id != sanitize_instance_id(self.id):
            raise ConfigError("id must contain only letters, numbers, dot, dash, or underscore")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ConfigError("name must be a non-empty string")
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
        self.stop_duration_min = _integer("stop_duration_min", self.stop_duration_min)
        if self.stop_duration_min < 0:
            raise ConfigError("stop_duration_min must be >= 0")
        if not isinstance(self.notify_enabled, bool):
            raise ConfigError("notify_enabled must be a boolean")
        if not isinstance(self.telegram_enabled, bool):
            raise ConfigError("telegram_enabled must be a boolean")
        if not isinstance(self.telegram_bot_token, str):
            raise ConfigError("telegram_bot_token must be a string")
        if not isinstance(self.telegram_chat_id, str):
            raise ConfigError("telegram_chat_id must be a string")
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
        if not isinstance(self.user_policies, dict):
            raise ConfigError("user_policies must be a mapping")
        for user, policy in self.user_policies.items():
            if not isinstance(user, str) or not user:
                raise ConfigError("user_policies keys must be non-empty usernames")
            UserPolicy.from_dict(policy)

    def base_url(self):
        return "http://%s:%s" % (self.host, self.port)

    def auth(self):
        return (self.webif_user, self.webif_pass)

    def policy_for(self, username):
        policy = self.user_policies.get(username, {})
        if username in self.exempt_users and not policy:
            return UserPolicy(action="ignore")
        return UserPolicy.from_dict(policy)

    def ensure_user_policy(self, username):
        if username not in self.user_policies:
            self.user_policies[username] = UserPolicy().to_dict()


class UserPolicy(object):
    def __init__(self, max_ecm_per_min=None, action="global",
                 stop_duration_min=None):
        self.max_ecm_per_min = max_ecm_per_min
        self.action = action or "global"
        self.stop_duration_min = stop_duration_min
        self.validate()

    @classmethod
    def from_dict(cls, data):
        if isinstance(data, UserPolicy):
            return data
        return cls(
            max_ecm_per_min=(data or {}).get("max_ecm_per_min"),
            action=(data or {}).get("action", "global"),
            stop_duration_min=(data or {}).get("stop_duration_min"),
        )

    def to_dict(self):
        return {
            "max_ecm_per_min": self.max_ecm_per_min,
            "action": self.action,
            "stop_duration_min": self.stop_duration_min,
        }

    def validate(self):
        if self.max_ecm_per_min in ("", None):
            self.max_ecm_per_min = None
        else:
            self.max_ecm_per_min = _number("user max_ecm_per_min", self.max_ecm_per_min)
            if self.max_ecm_per_min <= 0:
                raise ConfigError("user max_ecm_per_min must be greater than 0")
        if self.action not in USER_ACTIONS:
            raise ConfigError("user action must be one of: %s" % ", ".join(sorted(USER_ACTIONS)))
        if self.stop_duration_min in ("", None):
            self.stop_duration_min = None
        else:
            self.stop_duration_min = _integer("user stop_duration_min", self.stop_duration_min)
            if self.stop_duration_min < 0:
                raise ConfigError("user stop_duration_min must be >= 0")


class WebConfig(object):
    def __init__(self, bind_host="0.0.0.0", port=8787, admin_user="admin",
                 admin_password_hash=""):
        self.bind_host = bind_host
        self.port = port
        self.admin_user = admin_user
        self.admin_password_hash = admin_password_hash
        self.validate()

    @classmethod
    def from_dict(cls, data):
        merged = dict(WEB_DEFAULTS)
        merged.update(data or {})
        return cls(**merged)

    def to_dict(self):
        return {
            "bind_host": self.bind_host,
            "port": self.port,
            "admin_user": self.admin_user,
            "admin_password_hash": self.admin_password_hash,
        }

    def validate(self):
        if not isinstance(self.bind_host, str) or not self.bind_host:
            raise ConfigError("web bind_host must be a non-empty string")
        self.port = _integer("web port", self.port)
        if self.port < 1 or self.port > 65535:
            raise ConfigError("web port must be between 1 and 65535")
        if not isinstance(self.admin_user, str) or not self.admin_user.strip():
            raise ConfigError("admin_user must be a non-empty string")
        if not isinstance(self.admin_password_hash, str):
            raise ConfigError("admin_password_hash must be a string")


@dataclass
class VpnConfig(object):
    enabled: bool = False
    license_key: str = ""
    panel_fqdn: str = ""
    agent_id: str = ""
    wg_api_url: str = DEFAULT_WG_API_URL
    issue_key_url: str = ""
    oscam_checker_binary_url: str = DEFAULT_OSCAM_CHECKER_BINARY_URL
    bootstrap_key: str = ""
    server_key: str = ""
    wg_port: object = None
    wg_subnet: str = ""
    wg_listen_port: int = 51820
    status: str = ""
    enrolled_at: str = ""

    @classmethod
    def from_dict(cls, data):
        merged = dict(VPN_DEFAULTS)
        merged.update(data or {})
        merged["license_key"] = os.environ.get("RC_LICENSE_KEY", merged.get("license_key") or "")
        merged["panel_fqdn"] = os.environ.get("RC_PANEL_FQDN", merged.get("panel_fqdn") or "")
        merged["wg_api_url"] = os.environ.get("RC_WG_API_URL", merged.get("wg_api_url") or DEFAULT_WG_API_URL)
        merged["oscam_checker_binary_url"] = os.environ.get(
            "RC_OSCAM_CHECKER_URL",
            merged.get("oscam_checker_binary_url") or DEFAULT_OSCAM_CHECKER_BINARY_URL,
        )
        return cls(**merged)

    def __post_init__(self):
        self.validate()

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "license_key": self.license_key,
            "panel_fqdn": self.panel_fqdn,
            "agent_id": self.agent_id,
            "wg_api_url": self.wg_api_url,
            "issue_key_url": self.issue_key_url or self.default_issue_key_url(),
            "oscam_checker_binary_url": self.oscam_checker_binary_url,
            "bootstrap_key": self.bootstrap_key,
            "server_key": self.server_key,
            "wg_port": self.wg_port,
            "wg_subnet": self.wg_subnet,
            "wg_listen_port": self.wg_listen_port,
            "status": self.status,
            "enrolled_at": self.enrolled_at,
        }

    def validate(self):
        if not isinstance(self.enabled, bool):
            raise ConfigError("vpn enabled must be a boolean")
        for key in (
            "license_key",
            "panel_fqdn",
            "agent_id",
            "wg_api_url",
            "issue_key_url",
            "oscam_checker_binary_url",
            "bootstrap_key",
            "server_key",
            "wg_subnet",
            "status",
            "enrolled_at",
        ):
            if not isinstance(getattr(self, key), str):
                raise ConfigError("vpn %s must be a string" % key)
        if not self.wg_api_url:
            raise ConfigError("vpn wg_api_url must be a non-empty string")
        self.wg_api_url = self.wg_api_url.rstrip("/")
        if not self.issue_key_url:
            self.issue_key_url = self.default_issue_key_url()
        if self.wg_port in ("", None):
            self.wg_port = None
        else:
            self.wg_port = _integer("vpn wg_port", self.wg_port)
            if self.wg_port < 1 or self.wg_port > 65535:
                raise ConfigError("vpn wg_port must be between 1 and 65535")
        self.wg_listen_port = _integer("vpn wg_listen_port", self.wg_listen_port)
        if self.wg_listen_port < 1 or self.wg_listen_port > 65535:
            raise ConfigError("vpn wg_listen_port must be between 1 and 65535")

    def default_issue_key_url(self):
        return "%s/issue-key.php" % self.wg_api_url.rstrip("/")


class AppConfig(object):
    def __init__(self, web=None, instances=None, vpn=None, version=2):
        self.version = int(version)
        self.web = web if isinstance(web, WebConfig) else WebConfig.from_dict(web)
        self.vpn = vpn if isinstance(vpn, VpnConfig) else VpnConfig.from_dict(vpn)
        self.instances = [
            item if isinstance(item, InstanceConfig) else InstanceConfig.from_dict(item)
            for item in (instances or [])
        ]
        self.validate()

    @classmethod
    def from_dict(cls, data):
        if _looks_like_legacy_instance(data):
            return cls(instances=[data], web=WEB_DEFAULTS)
        return cls(
            version=(data or {}).get("version", 2),
            web=(data or {}).get("web", {}),
            vpn=(data or {}).get("vpn", {}),
            instances=(data or {}).get("instances", []),
        )

    def to_dict(self):
        return {
            "version": self.version,
            "web": self.web.to_dict(),
            "vpn": self.vpn.to_dict(),
            "instances": [instance.to_dict() for instance in self.instances],
        }

    def validate(self):
        seen = set()
        for instance in self.instances:
            if instance.id in seen:
                raise ConfigError("duplicate instance id: %s" % instance.id)
            seen.add(instance.id)

    def get_instance(self, instance_id=None):
        if not self.instances:
            raise ConfigError("no OSCam instances configured")
        if instance_id is None:
            return self.instances[0]
        for instance in self.instances:
            if instance.id == instance_id:
                return instance
        raise ConfigError("unknown instance: %s" % instance_id)

    def upsert_instance(self, instance):
        if not isinstance(instance, InstanceConfig):
            instance = InstanceConfig.from_dict(instance)
        for index, current in enumerate(self.instances):
            if current.id == instance.id:
                self.instances[index] = instance
                return
        self.instances.append(instance)

    def remove_instance(self, instance_id):
        before = len(self.instances)
        self.instances = [item for item in self.instances if item.id != instance_id]
        return len(self.instances) != before


def config_path(config_dir):
    return os.path.join(config_dir, CONFIG_FILENAME)


def load_config(config_dir=DEFAULT_CONFIG_DIR, logger=None):
    return load_app_config(config_dir, logger=logger).get_instance()


def load_app_config(config_dir=DEFAULT_CONFIG_DIR, logger=None):
    path = config_path(config_dir)
    _ensure_owner_only_if_exists(path, logger)
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
    except IOError as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc))
    except ValueError as exc:
        raise ConfigError("invalid JSON in %s: %s" % (path, exc))
    return AppConfig.from_dict(data)


def save_config(config, config_dir=DEFAULT_CONFIG_DIR):
    if isinstance(config, AppConfig):
        save_app_config(config, config_dir)
        return
    app = AppConfig(instances=[
        config if isinstance(config, InstanceConfig) else InstanceConfig.from_dict(config)
    ])
    save_app_config(app, config_dir)


def save_app_config(config, config_dir=DEFAULT_CONFIG_DIR):
    if not isinstance(config, AppConfig):
        config = AppConfig.from_dict(config)
    _atomic_write_json(config_path(config_dir), config.to_dict())


def create_empty_app_config(admin_password=None, web_port=8787, bind_host="0.0.0.0"):
    password = admin_password or secrets.token_urlsafe(14)
    return AppConfig(
        web=WebConfig(
            bind_host=bind_host,
            port=web_port,
            admin_user="admin",
            admin_password_hash=hash_password(password),
        ),
        instances=[],
    ), password


def hash_password(password, salt=None):
    if not isinstance(password, str) or not password:
        raise ConfigError("password must be a non-empty string")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt.encode("ascii"), 120000)
    return "pbkdf2_sha256$120000$%s$%s" % (salt, digest.hex())


def verify_password(password, stored_hash):
    try:
        algorithm, rounds_text, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     salt.encode("ascii"), int(rounds_text))
        return hmac.compare_digest(digest.hex(), expected)
    except Exception:
        return False


def sanitize_instance_id(value):
    text = str(value or "").strip().lower()
    result = []
    for char in text:
        if char.isalnum() or char in ("-", "_", "."):
            result.append(char)
        elif char.isspace():
            result.append("-")
    cleaned = "".join(result).strip(".-_")
    return cleaned or "oscam"


def instance_state_dir(config_dir, instance_id):
    return os.path.join(config_dir, "instances", sanitize_instance_id(instance_id))


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
    if isinstance(value, AppConfig):
        value = value.to_dict()
    if isinstance(value, InstanceConfig):
        value = value.to_dict()
    if isinstance(value, WebConfig):
        value = value.to_dict()
    if isinstance(value, VpnConfig):
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


def _looks_like_legacy_instance(data):
    return isinstance(data, dict) and "host" in data and "port" in data


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
