import sys
from pathlib import Path

import pandas as pd

from src import main as main_mod


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    content = ",".join(header) + "\n" + "\n".join(",".join(map(str, row)) for row in rows)
    path.write_text(content, encoding="utf-8")


def test_hard_commitments_are_exported(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    players = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2024-01-01-A", idx + 1, name, "Damage", 1] for idx, name in enumerate(players)],
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [[name, 1] for name in players],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason"],
        [["Nobody", "", "", 0, ""]],
    )

    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment", "Source", "Note"],
        [
            [name, "A" if idx < 3 else "B", "Start", "hard", "manual", ""]
            for idx, name in enumerate(players)
        ],
    )

    captured: dict[str, object] = {}

    def _fake_builder(df: pd.DataFrame, forced_assignments, **kwargs) -> pd.DataFrame:
        captured["forced_assignments"] = list(forced_assignments)
        rows = [
            {
                "PlayerName": item["PlayerName"],
                "Group": item["Group"],
                "Role": item["Role"],
                "NoShowOverall": 0.0,
                "NoShowRolling": 0.0,
                "risk_penalty": 0.0,
            }
            for item in forced_assignments
        ]
        return pd.DataFrame(rows)

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
        "--event-signups",
        "data/event_signups_next.csv",
        "--out",
        "generated",
    ]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    payload = captured["payload"]
    signup_pool = payload["signup_pool"]
    stats = signup_pool["stats"]

    assert stats["file_rows_total"] == len(players)
    assert stats["file_entries_total"] == len(players)
    assert stats["processed_entries_total"] == len(players)
    assert stats["hard_commit_rows_total"] == len(players)
    assert stats["forced_in_roster"] == len(players)
    assert stats["forced_total"] == len(players)

    file_entries = signup_pool["file_entries"]
    assert len(file_entries) == len(players)
    assert all("row_index" in entry for entry in file_entries)
    assert {entry["player"] for entry in file_entries} == set(players)

    forced_signups = signup_pool["forced_signups"]
    assert len(forced_signups) == len(players)
    assert {item["player"] for item in forced_signups} == set(players)

    event_meta = payload["event_signups"]
    assert event_meta["file_rows_total"] == len(players)
    assert event_meta["hard_commit_rows_total"] == len(players)

    forced_players = {
        p["display"]
        for p in payload["players"]
        if p.get("has_forced_signup") or p.get("forced_signup")
    }
    assert forced_players == set(players)

