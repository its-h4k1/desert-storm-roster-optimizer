from datetime import datetime, timezone
from types import SimpleNamespace

from src.main import _build_payload


class DummyConfig:
    HARD_SIGNUPS_ONLY = False


def test_payload_exports_reliability_block():
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
    )

    assert "reliability" in payload
    reliability = payload["reliability"]
    assert "players" not in reliability
    assert reliability["meta"]["reliability_start_date"]
