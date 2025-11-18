from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from src import main as main_mod


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.write_text(
        ",".join(header) + "\n" + "\n".join(",".join(map(str, row)) for row in rows),
        encoding="utf-8",
    )


def test_main_excludes_absent_players(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2024-01-01-A", 1, "PresentOne", "Damage", 1]],
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [["PresentOne", 1], ["AbsentOne", 1]],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason"],
        [["AbsentOne", "2000-01-01", "2100-01-01", 1, "Vacation"]],
    )

    captured: dict[str, list[str]] = {}

    def _fake_builder(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        captured["player_names"] = sorted(df["PlayerName"].tolist())
        return pd.DataFrame(
            {
                "PlayerName": df["PlayerName"],
                "Group": ["A"] * len(df),
                "Role": ["Start"] * len(df),
                "NoShowOverall": [0.0] * len(df),
                "NoShowRolling": [0.0] * len(df),
                "risk_penalty": [0.0] * len(df),
            }
        )

    def _noop_writer(out_dir, roster_df, json_payload):
        return None

    monkeypatch.setattr(main_mod, "build_deterministic_roster", _fake_builder)
    monkeypatch.setattr(main_mod, "_write_outputs", _noop_writer)

    argv = [
        "prog",
        "--events",
        "data/events.csv",
        "--alliance",
        "data/alliance.csv",
        "--absences",
        "data/absences.csv",
        "--out",
        "generated",
    ]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    assert captured["player_names"] == ["presentone"]


def test_main_supports_legacy_active_column(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2024-01-01-A", 1, "MemberOne", "Damage", 1]],
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "Active"],
        [["MemberOne", 1], ["FormerMember", 0]],
    )

    captured: dict[str, list[str]] = {}

    def _fake_builder(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        captured["player_names"] = sorted(df["PlayerName"].tolist())
        return pd.DataFrame(
            {
                "PlayerName": df["PlayerName"],
                "Group": ["A"] * len(df),
                "Role": ["Start"] * len(df),
                "NoShowOverall": [0.0] * len(df),
                "NoShowRolling": [0.0] * len(df),
                "risk_penalty": [0.0] * len(df),
            }
        )

    def _noop_writer(out_dir, roster_df, json_payload):
        return None

    monkeypatch.setattr(main_mod, "build_deterministic_roster", _fake_builder)
    monkeypatch.setattr(main_mod, "_write_outputs", _noop_writer)

    argv = [
        "prog",
        "--events",
        "data/events.csv",
        "--alliance",
        "data/alliance.csv",
        "--out",
        "generated",
    ]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    assert captured["player_names"] == ["memberone"]


def test_absences_export_and_filter(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2024-01-01-A", 1, "PresentOne", "Damage", 1]],
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [["PresentOne", 1], ["AbsentOne", 1]],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason"],
        [
            ["AbsentOne", "2000-01-01", "2100-01-01", 1, "Vacation"],
            ["FutureAway", "2100-01-01", "2100-02-01", 1, "Later"],
        ],
    )

    captured: dict[str, object] = {}

    def _fake_builder(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        captured["player_names"] = sorted(df["PlayerName"].tolist())
        return pd.DataFrame(
            {
                "PlayerName": df["PlayerName"],
                "Group": ["A"] * len(df),
                "Role": ["Start"] * len(df),
                "NoShowOverall": [0.0] * len(df),
                "NoShowRolling": [0.0] * len(df),
                "risk_penalty": [0.0] * len(df),
            }
        )

    def _capture_writer(out_dir, roster_df, json_payload):
        captured["payload"] = json_payload
        captured["roster"] = roster_df

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
        "--out",
        "generated",
    ]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    payload = captured.get("payload")
    assert payload, "json payload not captured"
    absences_block = payload.get("absences")
    assert absences_block["total_entries"] == 2
    active_canon = {p["canonical"] for p in absences_block.get("players", []) if p.get("is_active_next_event")}
    assert "absentone" in active_canon
    assert "futureaway" not in captured["player_names"]
