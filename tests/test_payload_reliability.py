from datetime import datetime, timezone
from types import SimpleNamespace

from src.main import _build_payload
from src.stats import PlayerReliability


class DummyConfig:
    HARD_SIGNUPS_ONLY = False


def test_payload_exports_reliability_block():
    reliability_players = {
        "Example": PlayerReliability(
            events=3, attendance=2, no_shows=1, early_cancels=0, late_cancels=0
        )
    }

    payload = _build_payload(
        signups=[],
        eligible_signups=[],
        responses=[],
        signup_states={},
        rosters={},
        args=SimpleNamespace(
            event_id="DS-TEST", event_date="2025-11-28", event_time="21:00", event_signups="data/event_signups_next.csv"
        ),
        event_datetime_local=datetime(2025, 11, 28, 21, 0, tzinfo=timezone.utc),
        signup_deadline_local=datetime(2025, 11, 27, 3, 0, tzinfo=timezone.utc),
        config=DummyConfig(),
        reliability_players=reliability_players,
    )

    assert "reliability" in payload
    players = payload["reliability"]["players"]
    assert players["Example"]["events"] == 3
    assert players["Example"]["attendance"] == 2
    assert players["Example"]["no_shows"] == 1
    assert players["Example"]["early_cancels"] == 0
    assert players["Example"]["late_cancels"] == 0
    assert payload["reliability"]["meta"]["reliability_start_date"]
