import sys
import json
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


def test_manual_hard_commitment_exports_forced_signup(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2025-01-01-A", 1, "BobbydyBob", "Damage", 1]],
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [["BobbydyBob", 1]],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason"],
        [],
    )

    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment", "Source", "Note"],
        [["BobbydyBob", "A", "Start", "hard", "manual", ""]],
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
    forced_list = signup_pool.get("forced_signups") or []
    assert forced_list == [
        {
            "player": "BobbydyBob",
            "canon": "bobbydybob",
            "group": "A",
            "role": "Start",
            "source": "manual",
            "note": "",
            "commitment": "hard",
            "overbooked": False,
        }
    ]

    forced_assignments = captured.get("forced_assignments") or []
    assert forced_assignments == [
        {"PlayerName": "bobbydybob", "Group": "A", "Role": "Start"}
    ]

    players = payload.get("players") or []
    assert len(players) == 1
    player = players[0]
    assert player["display"] == "BobbydyBob"
    assert player.get("forced_signup") == {
        "commitment": "hard",
        "source": "manual",
        "note": "",
        "overbooked": False,
    }
    assert player.get("has_forced_signup") is True
    assert player.get("event_signup") == {
        "group": "A",
        "role": "Start",
        "source": "manual",
        "note": "",
    }
    assert player.get("has_event_signup") is True

    players_by_slot = {(p["canon"], p["group"], p["role"]): p for p in players}
    forced_key = ("bobbydybob", "A", "Start")
    assert forced_key in players_by_slot
    slot_player = players_by_slot[forced_key]
    assert slot_player.get("has_forced_signup") is True
    assert slot_player.get("forced_signup", {}).get("commitment") == "hard"


def test_hard_commitment_lowercase_header(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    players = ["Alpha", "Bravo", "Charlie"]

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2025-05-01-A", idx + 1, name, "Damage", 1] for idx, name in enumerate(players)],
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [[name, 1] for name in players],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason"],
        [],
    )

    # Header komplett in lowercase – muss dennoch als hard commitment erkannt werden.
    _write_csv(
        data_dir / "event_signups_next.csv",
        ["playername", "group", "role", "commitment", "source", "note"],
        [
            [name, "A", "Start", "hard", "manual", "lc header"]
            for name in players
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
    forced_signups = signup_pool.get("forced_signups") or []
    assert len(forced_signups) == len(players)
    assert {item["player"] for item in forced_signups} == set(players)

    event_meta = payload["event_signups"]
    assert event_meta["hard_commitments"] == len(players)
    assert event_meta["hard_commit_rows_total"] == len(players)

    players_with_forced = {
        p["display"]
        for p in payload.get("players") or []
        if p.get("has_forced_signup") or p.get("forced_signup")
    }
    assert players_with_forced == set(players)


def test_multiple_builds_apply_new_hard_commitments(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    players_round1 = ["Alpha", "Bravo", "Charlie", "Delta"]

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2026-01-01-A", idx + 1, name, "Damage", 1] for idx, name in enumerate(players_round1)],
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [[name, 1] for name in players_round1],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason"],
        [],
    )

    def _fake_builder(df: pd.DataFrame, forced_assignments, **kwargs) -> pd.DataFrame:
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

    monkeypatch.setattr(main_mod, "build_deterministic_roster", _fake_builder)

    def _run_build():
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
        monkeypatch.setattr(sys, "argv", argv)
        main_mod.main()

    def _load_forced_signups() -> set[str]:
        latest = json.loads((tmp_path / "docs/out/latest.json").read_text(encoding="utf-8"))
        signup_pool = latest.get("signup_pool") or {}
        forced = signup_pool.get("forced_signups") or latest.get("forced_signups") or []
        return {item.get("player") for item in forced}

    # Runde 1: ein einziger Fixplatz
    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment", "Source", "Note"],
        [["Alpha", "A", "Start", "hard", "manual", ""]],
    )

    monkeypatch.chdir(tmp_path)
    _run_build()
    first_forced = _load_forced_signups()
    assert first_forced == {"Alpha"}

    # Runde 2: weiteren Fixplatz hinzufügen → Superset erwartet
    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment", "Source", "Note"],
        [
            ["Alpha", "A", "Start", "hard", "manual", ""],
            ["Bravo", "B", "Ersatz", "hard", "manual", ""],
        ],
    )

    _run_build()
    second_forced = _load_forced_signups()
    assert second_forced == {"Alpha", "Bravo"}
    assert first_forced.issubset(second_forced)

    # Beide latest.json-Varianten müssen denselben Inhalt haben (keine Stale-Caches)
    out_latest = (tmp_path / "out/latest.json").read_text(encoding="utf-8")
    docs_latest = (tmp_path / "docs/out/latest.json").read_text(encoding="utf-8")
    assert out_latest == docs_latest


def test_hard_commitment_prefers_signup_group_over_pref(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    filler_players = [f"Alpha{i}" for i in range(31)]
    target_player = "Switchy"
    all_players = filler_players + [target_player]

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2027-01-01-A", idx + 1, name, "Damage", 1] for idx, name in enumerate(all_players)],
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance", "PrefGroup"],
        [[name, 1, ""] for name in filler_players] + [[target_player, 1, "B"]],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason"],
        [],
    )

    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment", "Source", "Note"],
        [[name, "A", "Start", "hard", "manual", ""] for name in filler_players]
        + [[target_player, "A", "Start", "hard", "manual", ""]],
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

    forced_assignments = captured.get("forced_assignments") or []
    target = next(item for item in forced_assignments if item["PlayerName"] == "switchy")
    assert target["Group"] == "A"

    payload = captured.get("payload") or {}
    signup_pool = payload.get("signup_pool") or {}
    forced = signup_pool.get("forced_signups") or []
    target_forced = next(item for item in forced if item.get("player") == target_player)
    assert target_forced["group"] == "A"
    assert target_forced["overbooked"] is True

