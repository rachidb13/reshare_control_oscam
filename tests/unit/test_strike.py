from reshare_control.config import InstanceConfig
from reshare_control.parse import NO_READING
from reshare_control.state import UserStrikeState
from reshare_control.strike import evaluate_strike


def _config(**overrides):
    data = {
        "host": "127.0.0.1",
        "port": 8888,
        "max_ecm_per_min": 20,
        "strike_count": 3,
    }
    data.update(overrides)
    return InstanceConfig.from_dict(data)


def test_over_limit_increments_but_does_not_flag_before_threshold():
    result = evaluate_strike(21, UserStrikeState(), _config())

    assert result.state.consecutive_strikes == 1
    assert result.state.status == "ok"
    assert result.should_stop is False


def test_numeric_at_or_under_limit_resets_and_status_ok():
    current = UserStrikeState(consecutive_strikes=2, status="ok")

    result = evaluate_strike(20, current, _config())

    assert result.state.consecutive_strikes == 0
    assert result.state.status == "ok"
    assert result.should_stop is False


def test_no_reading_is_inert_but_updates_evaluation_time():
    current = UserStrikeState(
        consecutive_strikes=2,
        last_observed_ecm_min=33,
        last_evaluated_at="2026-07-07T10:00:00Z",
        status="ok",
    )

    result = evaluate_strike(
        NO_READING,
        current,
        _config(),
        evaluated_at="2026-07-07T10:05:00Z",
    )

    assert result.state.consecutive_strikes == 2
    assert result.state.last_observed_ecm_min == 33
    assert result.state.last_evaluated_at == "2026-07-07T10:05:00Z"
    assert result.state.status == "ok"
    assert result.should_stop is False


def test_status_flagged_only_at_consecutive_strike_threshold():
    config = _config(strike_count=3)
    state = UserStrikeState(consecutive_strikes=2, status="ok")

    result = evaluate_strike(25, state, config)

    assert result.state.consecutive_strikes == 3
    assert result.state.status == "flagged"
    assert result.should_stop is False


def test_stop_requires_auto_stop_enabled_and_eligible_user():
    flagged = UserStrikeState(consecutive_strikes=2, status="ok")

    detection_only = evaluate_strike(25, flagged, _config(auto_stop_enabled=False))
    enforcement = evaluate_strike(25, flagged, _config(auto_stop_enabled=True))
    exempt = evaluate_strike(
        25,
        UserStrikeState(consecutive_strikes=2, status="ok", exempt=True),
        _config(auto_stop_enabled=True),
    )
    already_stopped = evaluate_strike(
        25,
        UserStrikeState(consecutive_strikes=2, status="stopped"),
        _config(auto_stop_enabled=True),
        already_disabled=True,
    )

    assert detection_only.state.status == "flagged"
    assert detection_only.should_stop is False
    assert enforcement.should_stop is True
    assert exempt.should_stop is False
    assert already_stopped.should_stop is False
