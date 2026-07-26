import json
import os
import stat

from reshare_control.config import InstanceConfig
from reshare_control.enforce import (
    AUDIT_FILENAME,
    enable_account,
    list_account_users,
    set_account_disabled,
    stop_account,
)
from reshare_control.state import StateStore, UserStrikeState
from reshare_control.webif import FetchResult, OK


class FakeFetcher(object):
    def __init__(self):
        self.requests = []

    def get(self, path):
        self.requests.append(path)
        return FetchResult(OK, body="ok", http_status=200)


def _write_user_file(tmp_path, body):
    path = tmp_path / "oscam.user"
    path.write_text(body)
    os.chmod(str(path), 0o640)
    return path


def _config(tmp_path, **overrides):
    data = {
        "host": "127.0.0.1",
        "port": 8888,
        "base_path": str(tmp_path),
        "max_ecm_per_min": 20,
        "strike_count": 3,
    }
    data.update(overrides)
    return InstanceConfig.from_dict(data)


def test_set_account_disabled_edits_only_target_block_and_preserves_mode(tmp_path):
    path = _write_user_file(tmp_path, """[account]
user = alpha
pwd = one

[account]
user = bravo
pwd = two
disabled = 0
""")

    changed = set_account_disabled(str(tmp_path), "bravo", True)

    text = path.read_text()
    assert changed is True
    assert "user = alpha\npwd = one\n" in text
    assert "user = bravo\npwd = two\ndisabled = 1\n" in text
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o640


def test_list_account_users_reads_all_account_blocks(tmp_path):
    _write_user_file(tmp_path, """[account]
user = alpha
pwd = one

[reader]
label = ignored

[account]
user = bravo
disabled = 0
""")

    assert list_account_users(str(tmp_path)) == ["alpha", "bravo"]


def test_set_account_disabled_adds_missing_disabled_line_idempotently(tmp_path):
    path = _write_user_file(tmp_path, """[account]
user = alpha
pwd = one
""")

    first = set_account_disabled(str(tmp_path), "alpha", True)
    second = set_account_disabled(str(tmp_path), "alpha", True)

    assert first is True
    assert second is False
    assert path.read_text().count("disabled = 1") == 1


def test_stop_account_marks_state_stopped_reinits_and_audits(tmp_path):
    _write_user_file(tmp_path, """[account]
user = alpha
pwd = one
""")
    config = _config(tmp_path, auto_stop_enabled=True)
    store = StateStore(str(tmp_path))
    fetcher = FakeFetcher()
    state = UserStrikeState(
        consecutive_strikes=3,
        last_observed_ecm_min=27,
        last_evaluated_at="2026-07-07T10:00:00Z",
        status="flagged",
    )

    stop_account(
        config,
        str(tmp_path),
        "alpha",
        state,
        observed_ecm_min=27,
        fetcher=fetcher,
        timestamp="2026-07-07T10:00:00Z",
    )

    assert fetcher.requests == ["/userconfig.html?action=reinit"]
    assert state.status == "stopped"
    audit = (tmp_path / AUDIT_FILENAME).read_text().strip()
    record = json.loads(audit)
    assert record["action"] == "stop"
    assert record["user"] == "alpha"
    assert record["observed_ecm_min"] == 27
    assert record["threshold"] == 20.0
    assert record["strike_count"] == 3
    assert record["result"] == "ok"


def test_enable_account_reenables_reinits_resets_state_and_audits(tmp_path):
    _write_user_file(tmp_path, """[account]
user = alpha
pwd = one
disabled = 1
""")
    config = _config(tmp_path)
    store = StateStore(str(tmp_path))
    state = store.load()
    state.set_user("alpha", {
        "consecutive_strikes": 4,
        "last_observed_ecm_min": 31,
        "last_evaluated_at": "2026-07-07T10:00:00Z",
        "status": "stopped",
    })
    store.save(state)
    fetcher = FakeFetcher()

    enable_account(
        config,
        str(tmp_path),
        "alpha",
        store,
        fetcher=fetcher,
        timestamp="2026-07-07T10:05:00Z",
    )

    assert "disabled = 0" in (tmp_path / "oscam.user").read_text()
    assert fetcher.requests == ["/userconfig.html?action=reinit"]
    state = store.load().get_user("alpha")
    assert state.consecutive_strikes == 0
    assert state.status == "ok"
    records = [json.loads(line) for line in (tmp_path / AUDIT_FILENAME).read_text().splitlines()]
    assert records[-1]["action"] == "reinstate"
    assert records[-1]["strike_count"] == 4
