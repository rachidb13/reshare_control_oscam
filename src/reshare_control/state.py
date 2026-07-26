"""state.json persistence and advisory locking primitives."""

import contextlib
import json
import os
import stat
import tempfile


STATE_FILENAME = "state.json"
LOCK_FILENAME = ".state.lock"
STATE_VERSION = 1
VALID_STATUSES = set(["ok", "flagged", "stopped"])


class StateError(ValueError):
    """Raised when state.json is malformed or cannot be used."""


class UserStrikeState(object):
    def __init__(self, consecutive_strikes=0, last_observed_ecm_min=None,
                 last_evaluated_at=None, status="ok", exempt=False,
                 stopped_until=None, last_connected=None):
        self.consecutive_strikes = int(consecutive_strikes)
        self.last_observed_ecm_min = last_observed_ecm_min
        self.last_evaluated_at = last_evaluated_at
        self.status = status
        self.exempt = bool(exempt)
        self.stopped_until = stopped_until
        self.last_connected = last_connected
        self.validate()

    @classmethod
    def from_dict(cls, data):
        return cls(
            consecutive_strikes=data.get("consecutive_strikes", 0),
            last_observed_ecm_min=data.get("last_observed_ecm_min"),
            last_evaluated_at=data.get("last_evaluated_at"),
            status=data.get("status", "ok"),
            exempt=data.get("exempt", False),
            stopped_until=data.get("stopped_until"),
            last_connected=data.get("last_connected"),
        )

    def to_dict(self):
        return {
            "consecutive_strikes": self.consecutive_strikes,
            "last_observed_ecm_min": self.last_observed_ecm_min,
            "last_evaluated_at": self.last_evaluated_at,
            "status": self.status,
            "exempt": self.exempt,
            "stopped_until": self.stopped_until,
            "last_connected": self.last_connected,
        }

    def validate(self):
        if self.consecutive_strikes < 0:
            raise StateError("consecutive_strikes must be >= 0")
        if self.status not in VALID_STATUSES:
            raise StateError("status must be one of: %s" % ", ".join(sorted(VALID_STATUSES)))
        if self.last_observed_ecm_min is not None:
            if isinstance(self.last_observed_ecm_min, bool):
                raise StateError("last_observed_ecm_min must be numeric or null")
            if not isinstance(self.last_observed_ecm_min, (int, float)):
                raise StateError("last_observed_ecm_min must be numeric or null")
        if self.stopped_until is not None and not isinstance(self.stopped_until, str):
            raise StateError("stopped_until must be an ISO-8601 string or null")
        if self.last_connected is not None and not isinstance(self.last_connected, bool):
            raise StateError("last_connected must be a boolean or null")


class ReshareState(object):
    def __init__(self, users=None, version=STATE_VERSION):
        self.version = int(version)
        self.users = {}
        for name, record in (users or {}).items():
            if isinstance(record, UserStrikeState):
                self.users[name] = record
            else:
                self.users[name] = UserStrikeState.from_dict(record)
        self.validate()

    @classmethod
    def empty(cls):
        return cls()

    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls.empty()
        return cls(version=data.get("version", STATE_VERSION),
                   users=data.get("users", {}))

    def to_dict(self):
        return {
            "version": self.version,
            "users": dict((name, state.to_dict()) for name, state in self.users.items()),
        }

    def validate(self):
        if self.version != STATE_VERSION:
            raise StateError("unsupported state version: %s" % self.version)

    def get_user(self, username):
        return self.users.get(username)

    def set_user(self, username, user_state):
        if not isinstance(user_state, UserStrikeState):
            user_state = UserStrikeState.from_dict(user_state)
        self.users[username] = user_state


class StateStore(object):
    def __init__(self, config_dir):
        self.config_dir = config_dir
        self.path = os.path.join(config_dir, STATE_FILENAME)
        self.lock_path = os.path.join(config_dir, LOCK_FILENAME)

    def load(self):
        return load_state(self.path)

    def save(self, state):
        save_state(self.path, state)

    @contextlib.contextmanager
    def locked(self):
        with _advisory_lock(self.lock_path):
            yield

    def locked_update(self, updater):
        with self.locked():
            state = self.load()
            result = updater(state)
            if result is not None:
                state = result
            self.save(state)
            return state


def state_path(config_dir):
    return os.path.join(config_dir, STATE_FILENAME)


def load_state(path_or_config_dir):
    path = _resolve_state_path(path_or_config_dir)
    if not os.path.exists(path):
        return ReshareState.empty()
    _ensure_owner_only_if_exists(path)
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
    except IOError as exc:
        raise StateError("cannot read %s: %s" % (path, exc))
    except ValueError as exc:
        raise StateError("invalid JSON in %s: %s" % (path, exc))
    return ReshareState.from_dict(data)


def save_state(path_or_config_dir, state):
    path = _resolve_state_path(path_or_config_dir)
    if not isinstance(state, ReshareState):
        state = ReshareState.from_dict(state)
    _atomic_write_json(path, state.to_dict())


def _resolve_state_path(path_or_config_dir):
    if os.path.basename(path_or_config_dir) == STATE_FILENAME:
        return path_or_config_dir
    return os.path.join(path_or_config_dir, STATE_FILENAME)


def _ensure_owner_only_if_exists(path):
    if not os.path.exists(path):
        return
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        os.chmod(path, 0o600)


def _atomic_write_json(path, data):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, 0o700)
    fd, tmp_path = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=directory or ".")
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


@contextlib.contextmanager
def _advisory_lock(path):
    import fcntl

    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, 0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "r+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        pass
