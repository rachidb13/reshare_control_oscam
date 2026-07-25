import json
import os

from reshare_control.config import InstanceConfig, save_config
from reshare_control.parse import NO_READING
from reshare_control.poller import run_cycle
from reshare_control.state import StateStore
from reshare_control.webif import FetchResult, OK, TRANSPORT_ERROR


class FakeFetcher(object):
    def __init__(self, responses=None, statuses=None):
        self.queue = list(responses or [])
        if statuses:
            self.queue = list(statuses) + self.queue
        self.requests = []

    def get(self, path):
        self.requests.append(path)
        item = self.queue.pop(0)
        if isinstance(item, FetchResult):
            return item
        return FetchResult(OK, body=item, http_status=200)


def _config(**overrides):
    data = {
        "host": "127.0.0.1",
        "port": 8888,
        "max_ecm_per_min": 20,
        "strike_count": 3,
    }
    data.update(overrides)
    return InstanceConfig.from_dict(data)


def _body(users):
    return json.dumps({"oscam": {"userstats": {"user": users}}})


def _user(name, ecm, disabled="0"):
    data = {"name": name, "disabled": disabled}
    if ecm is not NO_READING:
        data["total_ecm_min"] = str(ecm)
    return data


def _store(tmp_path, config):
    save_config(config, str(tmp_path))
    return StateStore(str(tmp_path))


def test_consecutive_over_limit_cycles_flag_without_stopping(tmp_path):
    config = _config(strike_count=3, auto_stop_enabled=False)
    store = _store(tmp_path, config)
    fetcher = FakeFetcher([
        _body([_user("alpha", 25)]),
        _body([_user("alpha", 26)]),
        _body([_user("alpha", 27)]),
    ])

    for index in range(3):
        result = run_cycle(
            config,
            store,
            fetcher=fetcher,
            evaluated_at="2026-07-07T10:0%s:00Z" % index,
        )

    state = store.load().get_user("alpha")
    assert state.consecutive_strikes == 3
    assert state.status == "flagged"
    assert result.users[0].should_stop is False
    assert result.stopped_users == []


def test_single_spike_then_under_limit_resets_and_never_flags(tmp_path):
    config = _config(strike_count=2)
    store = _store(tmp_path, config)
    fetcher = FakeFetcher([
        _body([_user("alpha", 25)]),
        _body([_user("alpha", 10)]),
    ])

    run_cycle(config, store, fetcher=fetcher, evaluated_at="2026-07-07T10:00:00Z")
    run_cycle(config, store, fetcher=fetcher, evaluated_at="2026-07-07T10:05:00Z")

    state = store.load().get_user("alpha")
    assert state.consecutive_strikes == 0
    assert state.status == "ok"


def test_no_reading_outage_cycle_changes_no_user_standing(tmp_path):
    config = _config(strike_count=3)
    store = _store(tmp_path, config)
    fetcher = FakeFetcher([
        _body([_user("alpha", 25)]),
        FetchResult(TRANSPORT_ERROR, error="timeout", curl_exit=28),
    ])

    run_cycle(config, store, fetcher=fetcher, evaluated_at="2026-07-07T10:00:00Z")
    before = store.load().get_user("alpha").to_dict()
    result = run_cycle(config, store, fetcher=fetcher, evaluated_at="2026-07-07T10:05:00Z")
    after = store.load().get_user("alpha").to_dict()

    assert after["consecutive_strikes"] == before["consecutive_strikes"]
    assert after["status"] == before["status"]
    assert after["last_observed_ecm_min"] == before["last_observed_ecm_min"]
    assert after["last_evaluated_at"] == "2026-07-07T10:05:00Z"
    assert result.fetch_status == TRANSPORT_ERROR


def test_disabled_and_already_stopped_users_are_skipped(tmp_path):
    config = _config(strike_count=1, auto_stop_enabled=False)
    store = _store(tmp_path, config)
    stopped = store.load()
    stopped.set_user("stopped_user", {
        "consecutive_strikes": 7,
        "status": "stopped",
        "last_observed_ecm_min": 99,
        "last_evaluated_at": "2026-07-07T09:00:00Z",
    })
    store.save(stopped)
    fetcher = FakeFetcher([
        _body([
            _user("disabled_user", 99, disabled="1"),
            _user("stopped_user", 99),
            _user("active_user", 99),
        ])
    ])

    run_cycle(config, store, fetcher=fetcher, evaluated_at="2026-07-07T10:00:00Z")
    state = store.load()

    assert state.get_user("disabled_user") is None
    assert state.get_user("stopped_user").consecutive_strikes == 7
    assert state.get_user("stopped_user").status == "stopped"
    assert state.get_user("active_user").status == "flagged"
    assert state.get_user("active_user").consecutive_strikes == 1


def test_enforcement_on_stops_threshold_user_reinits_and_audits(tmp_path):
    config = _config(strike_count=1, auto_stop_enabled=True, base_path=str(tmp_path))
    store = _store(tmp_path, config)
    (tmp_path / "oscam.user").write_text("""[account]
user = alpha
pwd = one
""")
    fetcher = FakeFetcher([
        _body([_user("alpha", 25)]),
        FetchResult(OK, body="ok", http_status=200),
    ])

    result = run_cycle(config, store, fetcher=fetcher, evaluated_at="2026-07-07T10:00:00Z")

    assert fetcher.requests == ["/oscamapi.json?part=userstats", "/userconfig.html?action=reinit"]
    assert "disabled = 1" in (tmp_path / "oscam.user").read_text()
    assert store.load().get_user("alpha").status == "stopped"
    assert result.stopped_users == ["alpha"]
    assert (tmp_path / "audit.log").read_text()


def test_enforcement_off_and_exempt_users_do_not_stop(tmp_path):
    detect_only = _config(strike_count=1, auto_stop_enabled=False, base_path=str(tmp_path))
    detect_store = _store(tmp_path / "detect", detect_only)
    detect_fetcher = FakeFetcher([_body([_user("alpha", 25)])])

    detect_result = run_cycle(
        detect_only,
        detect_store,
        fetcher=detect_fetcher,
        evaluated_at="2026-07-07T10:00:00Z",
    )

    exempt_config = _config(
        strike_count=1,
        auto_stop_enabled=True,
        exempt_users=["trusted"],
        base_path=str(tmp_path),
    )
    exempt_store = _store(tmp_path / "exempt", exempt_config)
    exempt_fetcher = FakeFetcher([_body([_user("trusted", 99)])])

    exempt_result = run_cycle(
        exempt_config,
        exempt_store,
        fetcher=exempt_fetcher,
        evaluated_at="2026-07-07T10:05:00Z",
    )

    assert detect_result.stopped_users == []
    assert detect_store.load().get_user("alpha").status == "flagged"
    assert detect_fetcher.requests == ["/oscamapi.json?part=userstats"]
    assert exempt_result.stopped_users == []
    assert exempt_store.load().get_user("trusted").status == "flagged"
    assert exempt_fetcher.requests == ["/oscamapi.json?part=userstats"]
