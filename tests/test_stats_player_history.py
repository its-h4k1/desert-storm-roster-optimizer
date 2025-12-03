from __future__ import annotations

import pandas as pd
import pytest

from src.stats import compute_player_history
from src.utils import exp_decay_weight, parse_event_date


def test_last_event_uses_last_show_instead_of_last_assignment():
    events = pd.DataFrame(
        [
            {
                "EventID": "DS-2025-09-20-A",
                "PlayerName": "DevastatorJMI",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 1,
            },
            {
                "EventID": "DS-2025-10-01-A",
                "PlayerName": "DevastatorJMI",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 1,
            },
            {
                "EventID": "DS-2025-11-14-A",
                "PlayerName": "DevastatorJMI",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 0,
            },
        ]
    )

    hist = compute_player_history(events)
    player = hist.loc[hist["PlayerName"] == "devastatorjmi"].iloc[0]

    assert player["last_event"] == parse_event_date("DS-2025-10-01-A")
    assert player["last_noshow_event"] == parse_event_date("DS-2025-11-14-A")
    assert player["last_event"] != player["last_noshow_event"]


def test_all_shows_and_empty_event_do_not_create_noshow():
    events = pd.DataFrame(
        [
            {
                "EventID": "DS-2025-01-01-A",
                "PlayerName": "Alpha",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 1,
            },
            {
                "EventID": "DS-2025-01-08-A",
                "PlayerName": "Alpha",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 1,
            },
            # Platzhalter-Event ohne einen einzigen Show-Eintrag
            {
                "EventID": "DS-2025-02-01-A",
                "PlayerName": "Alpha",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 0,
            },
            {
                "EventID": "DS-2025-02-01-A",
                "PlayerName": "Beta",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 0,
            },
            {
                "EventID": "DS-2025-02-01-A",
                "PlayerName": "Gamma",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 0,
            },
        ]
    )

    hist = compute_player_history(
        events, reference_dt=parse_event_date("DS-2025-03-01-A"), half_life_days=30
    )

    player = hist.loc[hist["PlayerName"] == "alpha"].iloc[0]
    assert player["assignments_total"] == 2
    assert player["shows_total"] == 2
    assert player["noshows_total"] == 0
    assert player["noshow_rate"] == 0
    assert player["w_noshow_rate"] == 0


def test_mixed_history_matches_totals_and_weighted_rates():
    # 5 Shows, 1 No-Show mit langer Halbwertszeit → weighted ~ ungewichtet
    events = []
    for idx, teilgenommen in enumerate([1, 1, 0, 1, 1, 1], start=1):
        events.append(
            {
                "EventID": f"DS-2025-01-{idx:02d}-A",
                "PlayerName": "PlayerB",
                "RoleAtRegistration": "Start",
                "Teilgenommen": teilgenommen,
            }
        )
    events_df = pd.DataFrame(events)

    hist = compute_player_history(
        events_df,
        reference_dt=parse_event_date("DS-2025-02-15-A"),
        half_life_days=10_000,
    )

    player = hist.loc[hist["PlayerName"] == "playerb"].iloc[0]
    assert player["assignments_total"] == 6
    assert player["shows_total"] == 5
    assert player["noshows_total"] == 1
    assert player["noshow_rate"] == pytest.approx(1 / 6)
    assert player["w_noshow_rate"] == pytest.approx(1 / 6, rel=1e-4)


def test_old_noshow_decays_in_weighted_rate():
    reference_dt = parse_event_date("DS-2025-02-01-A")
    events = pd.DataFrame(
        [
            {
                "EventID": "DS-2024-12-01-A",
                "PlayerName": "PlayerC",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 0,
            },
            {
                "EventID": "DS-2025-01-25-A",
                "PlayerName": "PlayerC",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 1,
            },
            {
                "EventID": "DS-2025-01-31-A",
                "PlayerName": "PlayerC",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 1,
            },
        ]
    )

    hist = compute_player_history(
        events, reference_dt=reference_dt, half_life_days=10
    )

    player = hist.loc[hist["PlayerName"] == "playerc"].iloc[0]
    weights = [
        exp_decay_weight(parse_event_date("DS-2024-12-01-A"), now_dt=reference_dt, half_life_days=10),
        exp_decay_weight(parse_event_date("DS-2025-01-25-A"), now_dt=reference_dt, half_life_days=10),
        exp_decay_weight(parse_event_date("DS-2025-01-31-A"), now_dt=reference_dt, half_life_days=10),
    ]
    weighted_assignments = sum(weights)
    weighted_shows = weights[1] + weights[2]
    expected_rolling = 1.0 - weighted_shows / weighted_assignments

    assert player["noshows_total"] == 1
    assert player["noshow_rate"] == pytest.approx(1 / 3)
    assert player["w_noshow_rate"] == pytest.approx(expected_rolling)
    assert player["w_noshow_rate"] < player["noshow_rate"]


def test_off_roster_entries_do_not_count_as_assignment():
    events = pd.DataFrame(
        [
            {
                "EventID": "DS-2025-01-01-A",
                "PlayerName": "OptOut",
                "RoleAtRegistration": "Off",
                "Teilgenommen": 0,
            },
            {
                "EventID": "DS-2025-01-08-A",
                "PlayerName": "OptOut",
                "RoleAtRegistration": "Start",
                "Teilgenommen": 1,
            },
        ]
    )

    hist = compute_player_history(
        events, reference_dt=parse_event_date("DS-2025-02-01-A"), half_life_days=30
    )

    player = hist.loc[hist["PlayerName"] == "optout"].iloc[0]
    assert player["assignments_total"] == 1
    assert player["shows_total"] == 1
    assert player["noshows_total"] == 0
