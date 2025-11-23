import sys
from pathlib import Path

import pandas as pd

from src import main as main_mod


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    content = ",".join(header) + "\n" + "\n".join(",".join(map(str, row)) for row in rows)
    path.write_text(content, encoding="utf-8")


def _by_canon(entries: list[dict], canon: str) -> dict:
    for entry in entries:
        if str(entry.get("canon")) == canon:
            return entry
    raise AssertionError(f"canon not found: {canon}")


def test_alliance_overview_lists_all_members(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    players = [
        "StarterA",
        "BenchB",
        "Decliner",
        "Absentia",
        "MaybeLow",
    ]

    events = [
        ["DS-2030-01-01-A", 1, "StarterA", "Damage", 1],
        ["DS-2030-01-01-A", 2, "BenchB", "Damage", 1],
        ["DS-2030-01-01-A", 3, "Decliner", "Damage", 0],
        ["DS-2030-01-01-A", 4, "Absentia", "Damage", 1],
    ]
    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        events,
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [[name, 1] for name in players],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "Scope", "InAlliance"],
        [["Absentia", "2029-12-01", "2031-01-01", "next_event", 1]],
    )

    _write_csv(
        data_dir / "event_responses_next.csv",
        ["PlayerName", "Status", "Source", "Note"],
        [["Decliner", "decline", "manual", "busy"], ["MaybeLow", "no_response", "manual", ""]],
    )

    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment"],
        [["StarterA", "A", "Start", "hard"]],
    )

    captured: dict[str, object] = {}

    def _fake_builder(df: pd.DataFrame, forced_assignments, **kwargs) -> pd.DataFrame:
        captured["builder_pool"] = df.copy()
        return pd.DataFrame(
            [
                {"PlayerName": "startera", "Group": "A", "Role": "Start", "NoShowOverall": 0.0, "NoShowRolling": 0.0, "risk_penalty": 0.0},
                {"PlayerName": "benchb", "Group": "B", "Role": "Ersatz", "NoShowOverall": 0.0, "NoShowRolling": 0.0, "risk_penalty": 0.0},
            ]
        )

    def _capture_writer(out_dir, roster_df, json_payload):
        captured["payload"] = json_payload
        captured["roster_df"] = roster_df

    monkeypatch.setattr(main_mod, "build_deterministic_roster", _fake_builder)
    monkeypatch.setattr(main_mod, "_write_outputs", _capture_writer)

    argv = [
        "prog",
        "--events",
        "data/events.csv",
        "--alliance",
        "data/alliance.csv",
        "--absences",
        "data/absences.csv",
        "--event-responses",
        "data/event_responses_next.csv",
        "--event-signups",
        "data/event_signups_next.csv",
        "--out",
        "generated",
    ]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    payload = captured.get("payload") or {}
    overview = payload.get("alliance_next_event_overview", {})
    players_block = overview.get("players", [])

    assert len(players_block) == len(players)

    starter = _by_canon(players_block, "startera")
    bench = _by_canon(players_block, "benchb")
    decliner = _by_canon(players_block, "decliner")
    absent = _by_canon(players_block, "absentia")
    maybe_low = _by_canon(players_block, "maybelow")

    assert starter.get("roster_status") == "A-Start"
    assert bench.get("roster_status") == "B-Ersatz"
    assert decliner.get("event_status") == "decline"
    assert absent.get("is_absent_next_event") is True
    assert maybe_low.get("event_status") == "no_response"

    assert starter.get("contact_recommendation") == "yes"
    assert decliner.get("contact_recommendation") == "no"
    assert absent.get("contact_recommendation") == "no"
    assert maybe_low.get("contact_recommendation") == "maybe"

    assert overview.get("meta", {}).get("callup_min_attend_prob") == main_mod.load_callup_config()[0].callup_min_attend_prob
