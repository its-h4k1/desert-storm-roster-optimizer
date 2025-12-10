from datetime import date, datetime, timezone

from datetime import date, datetime, timezone

import pandas as pd

from src.effective_signups import EffectiveSignupState
from src.stats import (
    PlayerReliability,
    compute_player_history,
    compute_player_reliability,
    compute_role_probs,
)


def _sample_events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "EventID": "DS-2025-11-21-A",
                "PlayerName": "Ranger",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 0,
            },
            {
                "EventID": "DS-2025-11-28-A",
                "PlayerName": "Ranger",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 0,
            },
        ]
    )


def test_reliability_start_date_filters_events_from_history():
    events = _sample_events()
    cutoff = date(2025, 11, 28)
    reference_dt = datetime(2025, 12, 10, tzinfo=timezone.utc)

    history_filtered = compute_player_history(
        events, reliability_start_date=cutoff, reference_dt=reference_dt
    )
    assert len(history_filtered) == 1
    row = history_filtered.iloc[0]
    assert row["PlayerName"] == "ranger"
    assert row["assignments_total"] == 1
    assert row["noshows_total"] == 1
    assert row["last_noshow_event"].date() == cutoff

    history_all = compute_player_history(events, reliability_start_date=None, reference_dt=reference_dt)
    row_all = history_all.iloc[0]
    assert row_all["assignments_total"] == 2
    assert row_all["noshows_total"] == 2


def test_reliability_start_date_filters_role_probabilities():
    events = _sample_events()
    cutoff = date(2025, 11, 28)
    reference_dt = datetime(2025, 12, 10, tzinfo=timezone.utc)

    role_probs_filtered = compute_role_probs(
        events, reliability_start_date=cutoff, reference_dt=reference_dt
    )
    row_filtered = role_probs_filtered.iloc[0]
    assert row_filtered["start_assignments"] == 1
    assert row_filtered["start_noshow"] == 1

    role_probs_all = compute_role_probs(
        events, reliability_start_date=None, reference_dt=reference_dt
    )
    row_all = role_probs_all.iloc[0]
    assert row_all["start_assignments"] == 2
    assert row_all["start_noshow"] == 2


def test_compute_player_reliability_counts_cancels_and_shows():
    cutoff = date(2025, 11, 28)
    events = pd.DataFrame(
        [
            {
                "EventID": "DS-2025-11-21-A",
                "PlayerName": "Player A",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 0,
                "EffectiveSignupState": EffectiveSignupState.HARD_ACTIVE.value,
            },
            {
                "EventID": "DS-2025-11-28-A",
                "PlayerName": "Player A",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 1,
                "EffectiveSignupState": EffectiveSignupState.HARD_ACTIVE.value,
            },
            {
                "EventID": "DS-2025-12-05-A",
                "PlayerName": "Player A",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 0,
                "EffectiveSignupState": EffectiveSignupState.CANCELLED_LATE.value,
            },
            {
                "EventID": "DS-2025-11-28-A",
                "PlayerName": "Player B",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 0,
                "EffectiveSignupState": EffectiveSignupState.HARD_ACTIVE.value,
            },
            {
                "EventID": "DS-2025-12-05-A",
                "PlayerName": "Player B",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 0,
                "EffectiveSignupState": EffectiveSignupState.CANCELLED_EARLY.value,
            },
        ]
    )

    reliability = compute_player_reliability(
        events, reliability_start_date=cutoff, reference_dt=datetime(2025, 12, 10, tzinfo=timezone.utc)
    )

    assert reliability["player a"] == PlayerReliability(
        events=2, attendance=1, no_shows=0, early_cancels=0, late_cancels=1
    )
    assert reliability["player b"] == PlayerReliability(
        events=2, attendance=0, no_shows=1, early_cancels=1, late_cancels=0
    )
