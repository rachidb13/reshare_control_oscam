"""Pure strike evaluation for one user reading."""

from datetime import datetime, timezone

from .parse import NO_READING
from .state import UserStrikeState


class StrikeEvaluation(object):
    def __init__(self, state, should_stop=False):
        self.state = state
        self.should_stop = bool(should_stop)


def evaluate_strike(reading, state, config, evaluated_at=None, already_disabled=False):
    """Return a fresh strike state and stop decision for one reading."""
    when = evaluated_at or _utc_now()
    current = state or UserStrikeState()
    exempt = bool(current.exempt)
    was_stopped = current.status == "stopped"

    if reading is NO_READING:
        new_state = UserStrikeState(
            consecutive_strikes=current.consecutive_strikes,
            last_observed_ecm_min=current.last_observed_ecm_min,
            last_evaluated_at=when,
            status=current.status,
            exempt=exempt,
        )
        return StrikeEvaluation(new_state, False)

    if reading > config.max_ecm_per_min:
        strikes = current.consecutive_strikes + 1
    else:
        strikes = 0

    if was_stopped and already_disabled:
        status = "stopped"
    else:
        status = "flagged" if strikes >= config.strike_count else "ok"

    new_state = UserStrikeState(
        consecutive_strikes=strikes,
        last_observed_ecm_min=reading,
        last_evaluated_at=when,
        status=status,
        exempt=exempt,
    )
    should_stop = (
        config.auto_stop_enabled
        and strikes >= config.strike_count
        and not exempt
        and not already_disabled
        and status != "stopped"
    )
    return StrikeEvaluation(new_state, should_stop)


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
