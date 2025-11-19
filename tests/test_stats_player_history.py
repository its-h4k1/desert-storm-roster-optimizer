from __future__ import annotations

import pandas as pd

from src.stats import compute_player_history
from src.utils import parse_event_date


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
