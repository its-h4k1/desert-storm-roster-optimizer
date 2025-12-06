from pathlib import Path
import math
import sys

import pandas as pd

from src import main as main_mod
from src import utils as utils_mod


def test_builder_leaves_slots_empty_with_low_attendance(monkeypatch):
    df = pd.DataFrame(
        {
            "PlayerName": ["reliable", "solid", "risky"],
            "attend_prob": [0.95, 0.72, 0.2],
            "PrefGroup": ["A", "A", "A"],
            "PrefMode": ["hard", "", ""],
            "PrefBoost": [0.0, 0.0, 0.0],
            "risk_penalty": [0.0, 0.0, 0.0],
        }
    )

    roster = utils_mod.build_deterministic_roster(
        df,
        capacities_by_group_role={"A": {"Start": 2, "Ersatz": 0}, "B": {"Start": 0, "Ersatz": 0}},
        min_attend_start=0.7,
        min_attend_sub=0.5,
        allow_unfilled=True,
    )

    players = roster["PlayerName"].tolist()
    assert "reliable" in players
    assert "solid" in players
    assert "risky" not in players
    assert len(players) == 2


def test_builder_uses_group_specific_thresholds():
    df = pd.DataFrame(
        {
            "PlayerName": ["a_high", "a_low", "b_low"],
            "attend_prob": [0.8, 0.58, 0.35],
            "PrefGroup": ["A", "A", "B"],
            "PrefMode": ["hard", "soft", "soft"],
            "PrefBoost": [0.0, 0.0, 0.0],
            "risk_penalty": [0.0, 0.0, 0.0],
        }
    )

    roster = utils_mod.build_deterministic_roster(
        df,
        capacities_by_group_role={"A": {"Start": 1, "Ersatz": 0}, "B": {"Start": 1, "Ersatz": 0}},
        min_attend_start={"A": 0.7, "B": 0.3},
        min_attend_sub=0.0,
        allow_unfilled=True,
    )

    players_by_group = roster.groupby("Group")["PlayerName"].apply(list).to_dict()
    assert players_by_group.get("A", []) == ["a_high"]
    assert players_by_group.get("B", []) == ["b_low"]


def test_attendance_prob_and_status_flow(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write = lambda path, header, rows: path.write_text(
        ",".join(header) + "\n" + "\n".join(",".join(map(str, r)) for r in rows), encoding="utf-8"
    )

    _write(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [
            ["DS-2030-01-01-A", 1, "Hero", "Damage", 1],
            ["DS-2030-01-01-A", 2, "Risky", "Damage", 0],
        ],
    )
    _write(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [["Hero", 1], ["Risky", 1], ["Hardy", 1]],
    )
    _write(data_dir / "absences.csv", ["PlayerName", "From", "To", "InAlliance"], [])
    _write(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment"],
        [["Hardy", "A", "Start", "hard"], ["Hero", "A", "Start", "none"]],
    )
    _write(
        data_dir / "event_responses_next.csv",
        ["PlayerName", "Status"],
        [["Risky", "no_response"]],
    )

    captured: dict[str, object] = {}

    def _capture_writer(out_dir, roster_df, json_payload):
        captured["payload"] = json_payload
        captured["roster"] = roster_df

    monkeypatch.setattr(main_mod, "_write_outputs", _capture_writer)
    monkeypatch.setattr(main_mod, "STARTERS_PER_GROUP", 2)
    monkeypatch.setattr(main_mod, "SUBS_PER_GROUP", 0)
    monkeypatch.setenv("HARD_SIGNUPS_ONLY", "0")
    from src import config as config_mod

    monkeypatch.setattr(config_mod, "_CONFIG_CACHE", None)

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
        "--event-responses",
        "data/event_responses_next.csv",
        "--out",
        "generated",
    ]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    payload = captured.get("payload") or {}
    players = payload.get("players") or []

    hero = next(p for p in players if p.get("canon") == "hero")
    hardy = next(p for p in players if p.get("canon") == "hardy")
    risky = next((p for p in players if p.get("canon") == "risky"), {})

    assert hero.get("attend_prob", 0) > risky.get("attend_prob", 0)
    assert hardy.get("next_event_status") == "hard_commitment"
    stats = payload.get("event_responses", {}).get("stats", {})
    assert stats.get("no_responses", 0) == 1

    attendance = payload.get("attendance") or {}
    teams = attendance.get("teams") or {}
    team_a_meta = teams.get("A", {})
    assert team_a_meta.get("starters", {}).get("total", 0) >= 1
    assert attendance.get("threshold")


def test_team_a_fills_before_threshold():
    df = pd.DataFrame(
        {
            "PlayerName": ["strong", "mid", "risky"],
            "attend_prob": [0.95, 0.45, 0.35],
            "PrefGroup": ["A", "A", "B"],
            "PrefMode": ["hard", "soft", "soft"],
            "PrefBoost": [0.0, 0.0, 0.0],
            "risk_penalty": [0.0, 0.0, 0.0],
        }
    )

    roster = utils_mod.build_deterministic_roster(
        df,
        capacities_by_group_role={"A": {"Start": 2, "Ersatz": 0}, "B": {"Start": 2, "Ersatz": 0}},
        min_attend_start={"A": None, "B": 0.8},
        min_attend_sub=0.8,
        min_b_starters=utils_mod.MIN_B_STARTERS,
        allow_unfilled=True,
    )

    players_by_group = roster.groupby("Group")["PlayerName"].apply(list).to_dict()
    assert set(players_by_group.get("A", [])) == {"strong", "mid"}
    assert players_by_group.get("B", []) == ["risky"]
    b_stage = roster.loc[roster["PlayerName"] == "risky", "_selection_stage"].iat[0]
    assert b_stage == "B-start-fallback"


def test_team_b_uses_fallback_pool_when_needed():
    df = pd.DataFrame(
        {
            "PlayerName": ["high1", "high2", "high3", "high4", "high5", "low1", "low2"],
            "attend_prob": [0.95, 0.9, 0.85, 0.8, 0.7, 0.4, 0.35],
            "PrefGroup": ["A", "A", "A", "A", "", "", ""],
            "PrefMode": ["hard", "", "", "", "", "", ""],
            "PrefBoost": [0.0] * 7,
            "risk_penalty": [0.0] * 7,
        }
    )

    roster = utils_mod.build_deterministic_roster(
        df,
        capacities_by_group_role={"A": {"Start": 4, "Ersatz": 1}, "B": {"Start": 3, "Ersatz": 1}},
        min_attend_start={"A": None, "B": 0.6},
        min_attend_sub=0.6,
        min_b_starters=utils_mod.MIN_B_STARTERS,
        allow_unfilled=True,
    )

    b_starters = roster[(roster["Group"] == "B") & (roster["Role"] == "Start")]
    assert len(b_starters) == min(utils_mod.MIN_B_STARTERS, 3)
    fallback_names = set(b_starters.loc[b_starters["_selection_stage"] == "B-start-fallback", "PlayerName"].tolist())
    assert fallback_names == {"low1", "low2"}
    bench = roster[roster["Role"] == "Ersatz"]
    assert bench.empty


def test_attendance_targets_respect_slots(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    def _write(path, header, rows):
        path.write_text(
            ",".join(header)
            + "\n"
            + "\n".join(",".join(map(str, r)) for r in rows),
            encoding="utf-8",
        )

    cfg_text = """
attendance:
  attendance_target_fraction: 0.8
  min_start_A: 0.6
  min_start_B: 0.6
  min_bench_A: 0.5
  min_bench_B: 0.5
  target_expected_A:
    low: 18
    high: 26
  target_expected_B:
    low: 18
    high: 26
  hard_commit_floor: 0.9
  no_response_multiplier: 0.6
  high_reliability_balance_ratio: 1.8
"""
    (data_dir / "attendance_config.yml").write_text(cfg_text, encoding="utf-8")

    _write(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2030-01-01-A", 1, "Alpha", "Damage", 1], ["DS-2030-01-01-A", 2, "Bravo", "Damage", 0]],
    )
    _write(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [["Alpha", 1], ["Bravo", 1], ["Charlie", 1]],
    )
    _write(data_dir / "absences.csv", ["PlayerName", "From", "To", "InAlliance"], [])
    _write(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment"],
        [["Charlie", "A", "Start", "hard"], ["Alpha", "A", "Start", "none"]],
    )
    _write(
        data_dir / "event_responses_next.csv",
        ["PlayerName", "Status"],
        [["Bravo", "no_response"]],
    )

    captured: dict[str, object] = {}

    def _capture_writer(out_dir, roster_df, json_payload):
        captured["payload"] = json_payload
        captured["roster"] = roster_df

    monkeypatch.setattr(main_mod, "_write_outputs", _capture_writer)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--events",
            "data/events.csv",
            "--alliance",
            "data/alliance.csv",
            "--absences",
            "data/absences.csv",
            "--event-signups",
            "data/event_signups_next.csv",
            "--event-responses",
            "data/event_responses_next.csv",
            "--out",
            "generated",
        ],
    )

    main_mod.main()

    payload = captured.get("payload") or {}
    attendance = payload.get("attendance") or {}
    targets_by_team = attendance.get("targets_by_team") or {}
    slots_by_team = attendance.get("slots_by_team") or {}
    expected = attendance.get("expected_by_team") or {}
    diffs = attendance.get("target_diff") or {}

    assert targets_by_team.get("A") == 24
    assert targets_by_team.get("B") == 24
    assert targets_by_team["A"] <= slots_by_team.get("A", {}).get("max_slots", 0)
    assert targets_by_team["B"] <= slots_by_team.get("B", {}).get("max_slots", 0)

    assert math.isclose(
        diffs.get("A", 0.0),
        expected.get("A", {}).get("total", 0.0) - targets_by_team.get("A", 0),
        rel_tol=1e-6,
    )
    assert math.isclose(
        diffs.get("B", 0.0),
        expected.get("B", {}).get("total", 0.0) - targets_by_team.get("B", 0),
        rel_tol=1e-6,
    )


def test_b_fallback_tie_break_prefers_low_event_count(monkeypatch, tmp_path):
    df = pd.DataFrame(
        {
            "PlayerName": ["veteran", "newbie"],
            "attend_prob": [0.5, 0.5],
            "PrefGroup": ["B", "B"],
            "PrefMode": ["soft", "soft"],
            "PrefBoost": [0.0, 0.0],
            "risk_penalty": [0.0, 0.0],
            "events_seen": [10, 2],
        }
    )

    monkeypatch.chdir(tmp_path)

    roster = utils_mod.build_deterministic_roster(
        df,
        capacities_by_group_role={"A": {"Start": 0, "Ersatz": 0}, "B": {"Start": 1, "Ersatz": 0}},
        min_attend_start={"A": None, "B": 0.8},
        min_attend_sub=0.8,
        min_b_starters=1,
        allow_unfilled=True,
    )

    starters_b = roster[(roster["Group"] == "B") & (roster["Role"] == "Start")]
    assert starters_b.iloc[0]["PlayerName"] == "newbie"

    debug_path = Path("out") / "debug_selection.csv"
    debug_df = pd.read_csv(debug_path)
    diag = debug_df.set_index("canonical_name")
    assert diag.loc["veteran", "selection_stage"] == "B-start-fallback"
    assert diag.loc["newbie", "selection_stage"] == "B-start-fallback"
    assert diag.loc["veteran", "cutoff_reason"] in {"no slots left", "MIN_B_STARTERS reached"}
