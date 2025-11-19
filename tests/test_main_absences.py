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


def _get_debug_file_entries(block: dict | None) -> list[dict]:
    if not block or not isinstance(block, dict):
        return []
    entries = block.get("file_entries")
    if entries is None:
        entries = block.get("players")
    return entries or []


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
        ["PlayerName", "From", "To", "InAlliance", "Reason", "Scope"],
        [
            ["AbsentOne", "", "", 1, "Vacation", "next_event"],
            ["FutureAway", "2100-01-01", "2100-02-01", 1, "Later", ""],
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
    debug_block = payload.get("absence_debug")
    assert debug_block["raw_count"] == 2
    assert debug_block["active_for_next_event"] == 1
    debug_players = _get_debug_file_entries(debug_block)
    assert {p.get("canonical") for p in debug_players} == {"absentone", "futureaway"}
    assert {p.get("canonical") for p in debug_players if p.get("is_absent_next_event")}
    assert {p.get("canonical") for p in debug_players if p.get("is_absent_next_event")} == {"absentone"}


def test_absence_payload_ignores_former_members(monkeypatch, tmp_path):
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
        [["PresentOne", 1], ["FormerMember", 0]],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason", "Scope"],
        [
            ["PresentOne", "2024-01-01", "2024-12-31", 1, "Active absence", "next_event"],
            ["FormerMember", "2024-01-01", "2024-12-31", 0, "Historical", "next_event"],
        ],
    )

    captured: dict[str, object] = {}

    def _fake_builder(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
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
    assert absences_block["total_entries"] == 1
    assert {p.get("canonical") for p in absences_block.get("players", [])} == {"presentone"}

    debug_block = payload.get("absence_debug")
    assert debug_block["raw_count"] == 1
    assert debug_block["active_for_next_event"] == 1
    assert {p.get("canonical") for p in _get_debug_file_entries(debug_block)} == {"presentone"}


def test_absence_debug_aggregates_active_entries(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2025-11-14-A", 1, "ilishelbymf", "Damage", 1]],
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [["ilishelbymf", 1], ["PresentOne", 1]],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason", "Scope"],
        [
            ["ilishelbymf", "", "", 1, "muss es noch erklärt bekommen", "next_event"],
            ["ilishelbymf", "2024-01-01", "2024-01-05", 1, "historisch", ""],
        ],
    )

    captured: dict[str, object] = {}

    def _fake_builder(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
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

    monkeypatch.setattr(
        main_mod,
        "_infer_next_event_ts",
        lambda df: (pd.Timestamp("2025-11-21", tz=main_mod.TZ), {"source": "test"}),
    )
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

    payload = captured.get("payload") or {}
    debug_block = payload.get("absence_debug") or {}
    file_entries = _get_debug_file_entries(debug_block)
    assert len(file_entries) == 2
    aggregated = debug_block.get("next_event_absences") or []
    assert len(aggregated) == 1
    agg_entry = aggregated[0]
    assert agg_entry.get("canonical") == "ilishelbymf"
    assert agg_entry.get("active") is True
    ranges = agg_entry.get("ranges") or []
    assert len(ranges) == 1
    assert ranges[0].get("reason") == "muss es noch erklärt bekommen"
    stats = debug_block.get("stats") or {}
    assert stats.get("file_entries") == 2
    assert stats.get("unique_active_players") == 1


def test_absence_conflict_with_hard_commitment(monkeypatch, tmp_path):
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
        [["PresentOne", 1]],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason", "Scope"],
        [["PresentOne", "", "", 1, "Trip", "next_event"]],
    )

    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment", "Source", "Note"],
        [["PresentOne", "A", "Start", "hard", "manual", ""]],
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
        "--event-signups",
        "data/event_signups_next.csv",
        "--out",
        "generated",
    ]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    payload = captured.get("payload")
    assert payload, "json payload not captured"
    conflicts = payload.get("absence_conflicts") or []
    assert {c.get("canonical") for c in conflicts} == {"presentone"}
    assert captured["player_names"] == []


def test_absence_debug_entries_and_roster_flag(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2025-11-14-A", 1, "ilishelbymf", "Damage", 1]],
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [["ilishelbymf", 1], ["PresentOne", 1]],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason"],
        [["ilishelbymf", "2025-11-18", "2026-02-18", 1, "Trip"]],
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

    # Erzwinge stabile Event-Referenz für Absenzen
    monkeypatch.setattr(
        main_mod, "_infer_next_event_ts", lambda df: (pd.Timestamp("2025-11-21", tz=main_mod.TZ), {"source": "test"})
    )
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

    payload = captured.get("payload") or {}
    groups = payload.get("groups", {})
    players_in_groups = set()
    for g in ["A", "B"]:
        for role in ["Start", "Ersatz"]:
            players_in_groups.update(groups.get(g, {}).get(role, []))

    assert "ilishelbymf" not in players_in_groups

    absence_debug = payload.get("absence_debug", {})
    players_debug = _get_debug_file_entries(absence_debug)
    il_debug_entries = [p for p in players_debug if (p.get("canonical") == "ilishelbymf")]
    assert il_debug_entries, "ilishelbymf should appear in absence_debug.players"
    assert all(p.get("is_absent_next_event") for p in il_debug_entries)

    players = payload.get("players") or []
    il_entries = [p for p in players if (p.get("canon") == "ilishelbymf")]
    assert il_entries, "absent player metadata missing from payload"
    assert all(p.get("is_absent_next_event") for p in il_entries)


def test_hard_commitments_from_all_sources(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [
            ["DS-2024-01-01-A", 1, "ManualHard", "Damage", 1],
            ["DS-2024-01-01-A", 2, "CallupHard", "Damage", 1],
        ],
    )

    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [["ManualHard", 1], ["CallupHard", 1], ["SoftInfo", 1]],
    )

    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance", "Reason"],
        [],
    )

    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment", "Source", "Note"],
        [
            ["ManualHard", "A", "Start", "hard", "manual", "Ticket"],
            ["CallupHard", "B", "Ersatz", "hard", "callup-confirmed", "Callup"],
            ["SoftInfo", "B", "Start", "none", "manual", "Info"],
        ],
    )

    captured: dict[str, object] = {}

    def _fake_builder(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        forced_assignments = list(kwargs.get("forced_assignments") or [])
        captured["forced_assignments"] = forced_assignments
        if not forced_assignments:
            players = df["PlayerName"].tolist()
            groups = ["A"] * len(players)
            roles = ["Start"] * len(players)
        else:
            players = [item["PlayerName"] for item in forced_assignments]
            groups = [item.get("Group", "A") for item in forced_assignments]
            roles = [item.get("Role", "Start") for item in forced_assignments]
        return pd.DataFrame(
            {
                "PlayerName": players,
                "Group": groups,
                "Role": roles,
                "NoShowOverall": [0.0] * len(players),
                "NoShowRolling": [0.0] * len(players),
                "risk_penalty": [0.0] * len(players),
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
        "--event-signups",
        "data/event_signups_next.csv",
        "--out",
        "generated",
    ]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    payload = captured.get("payload") or {}
    forced_list = payload.get("forced_signups") or []
    forced_sources = {item.get("canon"): item.get("source") for item in forced_list}
    assert forced_sources.get("manualhard") == "manual"
    assert forced_sources.get("calluphard") == "callup-confirmed"
    assert len(forced_sources) == 2

    signup_meta = payload.get("signup_pool") or {}
    assert signup_meta.get("hard_commitments_total") == 2
    assert signup_meta.get("forced_total") == 2
    assert signup_meta.get("forced_in_roster") == 2

    players = payload.get("players") or []
    by_canon = {p.get("canon"): p for p in players}
    assert by_canon.get("manualhard", {}).get("has_forced_signup") is True
    assert by_canon.get("calluphard", {}).get("has_forced_signup") is True
    assert (by_canon.get("softinfo") or {}).get("has_forced_signup") is not True

    forced_assignments = captured.get("forced_assignments") or []
    assert {item.get("PlayerName") for item in forced_assignments} == {"manualhard", "calluphard"}
