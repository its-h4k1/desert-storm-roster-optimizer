"""Effective signup state calculation for the upcoming event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Dict, Iterable, List
from zoneinfo import ZoneInfo

from src.core_signups import Signup
from src.event_responses import EventResponse


ZURICH_TZ = ZoneInfo("Europe/Zurich")


class EffectiveSignupState(str, Enum):
    NONE = "none"
    HARD_ACTIVE = "hard_active"
    CANCELLED_EARLY = "cancelled_early"
    CANCELLED_LATE = "cancelled_late"


@dataclass(frozen=True)
class PlayerSignupState:
    state: EffectiveSignupState
    last_response: EventResponse | None = None


def compute_event_datetime_local(
    event_date: str | None,
    event_time: str | None,
    *,
    tz: ZoneInfo = ZURICH_TZ,
) -> datetime:
    """Build a timezone-aware local event datetime.

    Falls back to the next Friday 21:00 (Zurich) if no explicit date is provided.
    """

    now_local = datetime.now(tz)

    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except Exception:
            return None

    def _parse_time(value: str | None) -> time:
        if not value:
            return time(21, 0)
        try:
            return time.fromisoformat(value)
        except Exception:
            return time(21, 0)

    parsed_date = _parse_date(event_date)
    if parsed_date is None:
        weekday = now_local.weekday()  # Monday = 0
        days_ahead = (4 - weekday) % 7
        if days_ahead == 0 and now_local.time() >= time(21, 0):
            days_ahead = 7
        parsed_date = now_local.date() + timedelta(days=days_ahead)

    parsed_time = _parse_time(event_time)
    return datetime.combine(parsed_date, parsed_time, tzinfo=tz)


def signup_deadline_for_event(event_datetime_local: datetime, *, tz: ZoneInfo = ZURICH_TZ) -> datetime:
    """Signup deadline: Thursday 03:00 local before the event."""

    event_local = event_datetime_local.astimezone(tz)
    days_since_thursday = (event_local.weekday() - 3) % 7
    deadline_date = (event_local - timedelta(days=days_since_thursday)).date()
    return datetime.combine(deadline_date, time(3, 0), tzinfo=tz)


def _latest_response_by_canon(responses: Iterable[EventResponse]) -> Dict[str, EventResponse]:
    def _key(resp: EventResponse) -> datetime:
        if resp.response_time is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        return resp.response_time

    latest: Dict[str, EventResponse] = {}
    for resp in responses:
        canon = resp.canon
        if not canon:
            continue
        current = latest.get(canon)
        if current is None or _key(resp) >= _key(current):
            latest[canon] = resp
    return latest


def determine_effective_signup_states(
    *,
    signups: List[Signup],
    responses: List[EventResponse],
    event_datetime_local: datetime,
) -> Dict[str, PlayerSignupState]:
    """Combine hard signups + responses into a per-player effective state."""

    deadline = signup_deadline_for_event(event_datetime_local)
    cancellations = [r for r in responses if r.status == "cancelled"]
    latest_cancellation_by_canon = _latest_response_by_canon(cancellations)
    latest_response_by_canon = _latest_response_by_canon(responses)

    states: Dict[str, PlayerSignupState] = {}

    for signup in signups:
        canon = signup.canon
        last_response = latest_response_by_canon.get(canon)
        cancellation = latest_cancellation_by_canon.get(canon)
        if cancellation is None:
            states[canon] = PlayerSignupState(
                state=EffectiveSignupState.HARD_ACTIVE,
                last_response=last_response,
            )
            continue

        resp_time = cancellation.response_time
        if resp_time is None:
            state = EffectiveSignupState.CANCELLED_LATE
        else:
            resp_local = resp_time.astimezone(ZURICH_TZ)
            state = (
                EffectiveSignupState.CANCELLED_EARLY
                if resp_local < deadline
                else EffectiveSignupState.CANCELLED_LATE
            )
        states[canon] = PlayerSignupState(state=state, last_response=cancellation)

    for canon, resp in latest_response_by_canon.items():
        if canon in states:
            continue
        states[canon] = PlayerSignupState(
            state=EffectiveSignupState.NONE, last_response=resp
        )

    return states


__all__ = [
    "EffectiveSignupState",
    "PlayerSignupState",
    "compute_event_datetime_local",
    "signup_deadline_for_event",
    "determine_effective_signup_states",
]
