import json
import sys
from pathlib import Path

import pandas as pd

from src import main as main_mod


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    content = ",".join(header) + "\n" + "\n".join(",".join(map(str, row)) for row in rows)
    path.write_text(content, encoding="utf-8")


def test_decline_removes_player_from_pool(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    players = ["Alpha", "Bravo"]
    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2027-01-01-A", idx + 1, name, "Damage", 1] for idx, name in enumerate(players)],
    )
    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [[name, 1] for name in players],
    )
    _write_csv(data_dir / "absences.csv", ["PlayerName", "From", "To", "InAlliance"], [])
    _write_csv(
        data_dir / "event_responses_next.csv",
        ["PlayerName", "Status", "Source", "Note"],
        [["Bravo", "decline", "manual", ""]],
    )

    captured: dict[str, object] = {}

    def _fake_builder(df: pd.DataFrame, forced_assignments, **kwargs) -> pd.DataFrame:
        captured["builder_pool"] = df.copy()
        rows = []
        for row in df.itertuples(index=False):
            rows.append(
                {
                    "PlayerName": getattr(row, "PlayerName"),
                    "Group": "A",
                    "Role": "Start",
                    "NoShowOverall": 0.0,
                    "NoShowRolling": 0.0,
                    "risk_penalty": getattr(row, "risk_penalty", 0.0),
                }
            )
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
        "--event-responses",
        "data/event_responses_next.csv",
        "--out",
        "generated",
    ]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    builder_pool = captured.get("builder_pool")
    assert builder_pool is not None
    assert set(builder_pool["PlayerName"].tolist()) == {"alpha"}  # bravo entfernt

    payload = captured.get("payload") or {}
    event_responses = payload.get("event_responses") or {}
    removed = event_responses.get("removed_from_pool") or []
    assert {item.get("canonical") for item in removed} == {"bravo"}


def test_no_response_penalty_export(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    players = ["Alpha", "Bravo"]
    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2028-02-02-A", idx + 1, name, "Damage", 1] for idx, name in enumerate(players)],
    )
    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [[name, 1] for name in players],
    )
    _write_csv(data_dir / "absences.csv", ["PlayerName", "From", "To", "InAlliance"], [])
    _write_csv(
        data_dir / "event_responses_next.csv",
        ["PlayerName", "Status", "Source", "Note"],
        [["Alpha", "no_response", "manual", "keine Rückmeldung"]],
    )

    captured: dict[str, object] = {}

    def _fake_builder(df: pd.DataFrame, forced_assignments, **kwargs) -> pd.DataFrame:
        captured["builder_pool"] = df.copy()
        rows = []
        for row in df.itertuples(index=False):
            rows.append(
                {
                    "PlayerName": getattr(row, "PlayerName"),
                    "Group": "A",
                    "Role": "Start",
                    "NoShowOverall": 0.0,
                    "NoShowRolling": 0.0,
                    "risk_penalty": getattr(row, "risk_penalty", 0.0),
                }
            )
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
        "--event-responses",
        "data/event_responses_next.csv",
        "--out",
        "generated",
    ]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    builder_pool = captured.get("builder_pool")
    assert builder_pool is not None
    risk_by_player = dict(zip(builder_pool["PlayerName"].tolist(), builder_pool["risk_penalty"].tolist()))
    assert risk_by_player.get("alpha", 0) > risk_by_player.get("bravo", 0)

    payload = captured.get("payload") or {}
    players = payload.get("players") or []
    alpha = next((p for p in players if p.get("canon") == "alpha"), None)
    assert alpha is not None
    assert alpha.get("event_response", {}).get("status") == "no_response"
    penalties = payload.get("event_responses", {}).get("penalty_applied") or []
    assert any(item.get("canonical") == "alpha" for item in penalties)


def test_missing_event_responses_file(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    players = ["Alpha", "Bravo"]
    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2029-03-03-A", idx + 1, name, "Damage", 1] for idx, name in enumerate(players)],
    )
    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [[name, 1] for name in players],
    )
    _write_csv(data_dir / "absences.csv", ["PlayerName", "From", "To", "InAlliance"], [])

    captured: dict[str, object] = {}

    def _fake_builder(df: pd.DataFrame, forced_assignments, **kwargs) -> pd.DataFrame:
        captured["builder_pool"] = df.copy()
        return pd.DataFrame(
            [
                {
                    "PlayerName": getattr(row, "PlayerName"),
                    "Group": "A",
                    "Role": "Start",
                    "NoShowOverall": 0.0,
                    "NoShowRolling": 0.0,
                    "risk_penalty": getattr(row, "risk_penalty", 0.0),
                }
                for row in df.itertuples(index=False)
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
        "--out",
        "generated",
    ]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    payload = captured.get("payload") or {}
    responses_meta = payload.get("event_responses", {}).get("stats") or {}
    assert responses_meta.get("file_entries", 0) == 0
    # No penalties or removals should be applied when the file is missing/empty.
    assert not payload.get("event_responses", {}).get("penalty_applied")
    assert not payload.get("event_responses", {}).get("removed_from_pool")

