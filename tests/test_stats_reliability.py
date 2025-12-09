from datetime import date, datetime, timezone

import pandas as pd

from src.stats import compute_player_history, compute_role_probs


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
