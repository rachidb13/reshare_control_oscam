"""Least-intrusive OSCAM account enforcement and audit records."""

from datetime import datetime, timezone
import json
import os
import stat
import tempfile

from .state import UserStrikeState
from .webif import OK, reinit


OSCAM_USER_FILENAME = "oscam.user"
AUDIT_FILENAME = "audit.log"


class EnforcementError(RuntimeError):
    """Raised when an OSCAM account cannot be safely edited or applied."""


def set_account_disabled(base_path, username, disabled):
    """Set disabled=1/0 for exactly one OSCAM [account] block."""
    path = os.path.join(base_path, OSCAM_USER_FILENAME)
    try:
        with open(path, "r") as fh:
            lines = fh.readlines()
    except IOError as exc:
        raise EnforcementError("cannot read %s: %s" % (path, exc))

    blocks = _account_blocks(lines)
    target = None
    for block in blocks:
        if _block_username(lines[block[0]:block[1]]) == username:
            target = block
            break
    if target is None:
        raise EnforcementError("account not found in %s: %s" % (path, username))

    desired = "1" if disabled else "0"
    changed = _set_disabled_in_block(lines, target[0], target[1], desired)
    if not changed:
        return False
    _atomic_write_preserving_metadata(path, lines)
    return True


def stop_account(config, config_dir, username, user_state, observed_ecm_min,
                 fetcher=None, timestamp=None):
    """Disable an account, reinit OSCAM, update state, and audit the stop."""
    when = timestamp or _utc_now()
    result = "ok"
    try:
        set_account_disabled(config.base_path, username, True)
        reinit_result = reinit(fetcher or config.base_url(), auth=config.auth(),
                               timeout_s=config.request_timeout_s)
        if reinit_result.status != OK:
            result = "error:reinit:%s" % reinit_result.status
            raise EnforcementError(result)
        user_state.status = "stopped"
    except Exception as exc:
        result = "error:%s" % exc
        append_audit_record(
            config_dir,
            action="stop",
            user=username,
            observed_ecm_min=observed_ecm_min,
            threshold=config.max_ecm_per_min,
            strike_count=user_state.consecutive_strikes,
            result=result,
            timestamp=when,
        )
        raise

    append_audit_record(
        config_dir,
        action="stop",
        user=username,
        observed_ecm_min=observed_ecm_min,
        threshold=config.max_ecm_per_min,
        strike_count=user_state.consecutive_strikes,
        result=result,
        timestamp=when,
    )
    return True


def enable_account(config, config_dir, username, store, fetcher=None, timestamp=None):
    """Re-enable an account, reinit OSCAM, reset state, and audit recovery."""
    when = timestamp or _utc_now()
    with store.locked():
        state = store.load()
        previous = state.get_user(username) or UserStrikeState()
        pre_reset_strikes = previous.consecutive_strikes
        observed = previous.last_observed_ecm_min
        set_account_disabled(config.base_path, username, False)
        reinit_result = reinit(fetcher or config.base_url(), auth=config.auth(),
                               timeout_s=config.request_timeout_s)
        if reinit_result.status != OK:
            append_audit_record(
                config_dir,
                action="reinstate",
                user=username,
                observed_ecm_min=observed,
                threshold=config.max_ecm_per_min,
                strike_count=pre_reset_strikes,
                result="error:reinit:%s" % reinit_result.status,
                timestamp=when,
            )
            raise EnforcementError("reinit failed: %s" % reinit_result.status)
        state.set_user(username, UserStrikeState(
            consecutive_strikes=0,
            last_observed_ecm_min=observed,
            last_evaluated_at=when,
            status="ok",
            exempt=username in config.exempt_users,
        ))
        store.save(state)
        append_audit_record(
            config_dir,
            action="reinstate",
            user=username,
            observed_ecm_min=observed,
            threshold=config.max_ecm_per_min,
            strike_count=pre_reset_strikes,
            result="ok",
            timestamp=when,
        )
    return True


def append_audit_record(config_dir, action, user, observed_ecm_min, threshold,
                        strike_count, result, timestamp=None):
    directory = config_dir
    if not os.path.isdir(directory):
        os.makedirs(directory, 0o700)
    path = os.path.join(directory, AUDIT_FILENAME)
    record = {
        "timestamp": timestamp or _utc_now(),
        "action": action,
        "user": user,
        "observed_ecm_min": observed_ecm_min,
        "threshold": threshold,
        "strike_count": strike_count,
        "result": result,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a") as fh:
            fh.write(json.dumps(record, sort_keys=True))
            fh.write("\n")
    finally:
        pass


def _account_blocks(lines):
    blocks = []
    index = 0
    while index < len(lines):
        if _section_name(lines[index]) == "account":
            start = index
            index += 1
            while index < len(lines) and _section_name(lines[index]) is None:
                index += 1
            blocks.append((start, index))
            continue
        index += 1
    return blocks


def _section_name(line):
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped[1:-1].strip().lower()
    return None


def _block_username(block_lines):
    for line in block_lines:
        key, value = _key_value(line)
        if key == "user":
            return value
    return None


def _set_disabled_in_block(lines, start, end, desired):
    insert_at = end
    for index in range(start + 1, end):
        key, value = _key_value(lines[index])
        if key != "disabled":
            continue
        if value == desired:
            return False
        newline = "\n" if lines[index].endswith("\n") else ""
        prefix = lines[index].split("=", 1)[0].rstrip()
        lines[index] = "%s = %s%s" % (prefix, desired, newline)
        return True
    if insert_at > 0 and insert_at <= len(lines):
        if insert_at == len(lines) and lines and not lines[-1].endswith("\n"):
            lines[-1] = lines[-1] + "\n"
    lines.insert(insert_at, "disabled = %s\n" % desired)
    return True


def _key_value(line):
    text = line.strip()
    if not text or text.startswith("#") or text.startswith(";") or "=" not in text:
        return None, None
    key, value = text.split("=", 1)
    return key.strip().lower(), value.strip()


def _atomic_write_preserving_metadata(path, lines):
    directory = os.path.dirname(path) or "."
    st = os.stat(path)
    mode = stat.S_IMODE(st.st_mode)
    fd, tmp_path = tempfile.mkstemp(prefix=".oscam.user.", suffix=".tmp", dir=directory)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as fh:
            fh.writelines(lines)
        try:
            os.chown(tmp_path, st.st_uid, st.st_gid)
        except OSError:
            pass
        os.replace(tmp_path, path)
        os.chmod(path, mode)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
