from datetime import datetime
from zoneinfo import ZoneInfo

from src.core_signups import Signup
from src.effective_signups import (
    EffectiveSignupState,
    compute_event_datetime_local,
    determine_effective_signup_states,
)
from src.event_responses import EventResponse


ZRH = ZoneInfo("Europe/Zurich")


def _signup(name: str) -> Signup:
    return Signup(
        name=name,
        canon=name.lower(),
        group_wish="",
        role_wish="",
        commitment="hard",
        source="manual",
        note="",
    )


def _response(name: str, status: str, ts: datetime | None) -> EventResponse:
    return EventResponse(
        name=name,
        canon=name.lower(),
        status=status,
        response_time=ts,
        note="",
        source="manual",
    )


def test_effective_states_respect_deadline():
    event_dt = compute_event_datetime_local("2024-12-06", "21:00")

    early_cancel = datetime(2024, 12, 5, 1, 0, tzinfo=ZRH)
    late_cancel = datetime(2024, 12, 5, 12, 0, tzinfo=ZRH)

    signups = [_signup("Alpha"), _signup("Bravo")]
    responses = [
        _response("Alpha", "cancelled", early_cancel),
        _response("Bravo", "cancelled", late_cancel),
        _response("Delta", "no_response", None),
    ]

    states = determine_effective_signup_states(
        signups=signups,
        responses=responses,
        event_datetime_local=event_dt,
    )

    assert states["alpha"].state is EffectiveSignupState.CANCELLED_EARLY
    assert states["alpha"].last_response.response_time == early_cancel
    assert states["bravo"].state is EffectiveSignupState.CANCELLED_LATE
    assert states["delta"].state is EffectiveSignupState.NONE


def test_non_cancelled_hard_signups_remain_active():
    event_dt = compute_event_datetime_local("2024-12-06", "21:00")

    signups = [_signup("Echo"), _signup("Foxtrot")]
    responses = [_response("Echo", "no_response", None)]

    states = determine_effective_signup_states(
        signups=signups,
        responses=responses,
        event_datetime_local=event_dt,
    )

    assert states["echo"].state is EffectiveSignupState.HARD_ACTIVE
    assert states["foxtrot"].state is EffectiveSignupState.HARD_ACTIVE
