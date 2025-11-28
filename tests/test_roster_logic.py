from __future__ import annotations

from dataclasses import replace
import sys
from pathlib import Path

import pandas as pd

from src import main as main_mod
from src import utils as utils_mod
from src import callup_config as callup_cfg


def test_b_starters_use_threshold_when_supply_is_high():
    df = pd.DataFrame(
        {
            "PlayerName": ["b_good_one", "b_good_two", "b_low"],
            "attend_prob": [0.9, 0.8, 0.4],
            "PrefGroup": ["B", "B", "B"],
            "PrefMode": ["soft", "soft", "soft"],
            "PrefBoost": [0.0, 0.0, 0.0],
            "risk_penalty": [0.0, 0.0, 0.0],
        }
    )

    roster = utils_mod.build_deterministic_roster(
        df,
        capacities_by_group_role={"A": {"Start": 0, "Ersatz": 0}, "B": {"Start": 2, "Ersatz": 0}},
        min_attend_start={"A": None, "B": 0.6},
        min_attend_sub=0.0,
        min_b_starters=2,
        allow_unfilled=True,
    )

    picked = roster[roster["Group"] == "B"]["PlayerName"].tolist()
    assert picked == ["b_good_one", "b_good_two"]
    assert all(name != "b_low" for name in picked)
    assert roster["_selection_stage"].unique().tolist() == ["B-start-main"]


def test_b_starters_fill_with_fallbacks_when_needed():
    df = pd.DataFrame(
        {
            "PlayerName": ["b_anchor", "b_fallback_one", "b_fallback_two"],
            "attend_prob": [0.75, 0.3, 0.2],
            "PrefGroup": ["B", "B", "B"],
            "PrefMode": ["soft", "soft", "soft"],
            "PrefBoost": [0.0, 0.0, 0.0],
            "risk_penalty": [0.0, 0.0, 0.0],
        }
    )

    roster = utils_mod.build_deterministic_roster(
        df,
        capacities_by_group_role={"A": {"Start": 0, "Ersatz": 0}, "B": {"Start": 3, "Ersatz": 0}},
        min_attend_start={"A": None, "B": 0.6},
        min_attend_sub=0.0,
        min_b_starters=3,
        allow_unfilled=True,
    )

    starters_b = roster[roster["Group"] == "B"]
    assert len(starters_b) == 3
    assert "b_anchor" in starters_b["PlayerName"].tolist()

    fallback_rows = starters_b[starters_b["_selection_stage"] == "B-start-fallback"]
    assert set(fallback_rows["PlayerName"].tolist()) == {"b_fallback_one", "b_fallback_two"}


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.write_text(
        ",".join(header) + "\n" + "\n".join(",".join(map(str, row)) for row in rows),
        encoding="utf-8",
    )


def _make_callup_config(**overrides):
    return replace(callup_cfg.DEFAULT_CALLOUP_CONFIG, **overrides)


def _fake_builder_capture(df: pd.DataFrame, captured: dict) -> pd.DataFrame:
    captured["builder_players"] = sorted(df["PlayerName"].tolist())
    return pd.DataFrame({
        "PlayerName": df["PlayerName"],
        "Group": ["A"] * len(df),
        "Role": ["Start"] * len(df),
        "_selection_stage": ["test"] * len(df),
    })


def test_callups_only_mode_allows_full_alliance_pool(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2030-01-01-A", 1, "SignupHero", "Damage", 1]],
    )
    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [["SignupHero", 1], ["FreeAgent", 1]],
    )
    _write_csv(data_dir / "absences.csv", ["PlayerName", "From", "To", "InAlliance"], [])
    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment"],
        [["SignupHero", "A", "Start", "none"]],
    )
    _write_csv(data_dir / "event_responses_next.csv", ["PlayerName", "Status"], [])

    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(main_mod, "build_deterministic_roster", lambda df, **_: _fake_builder_capture(df, captured))
    monkeypatch.setattr(main_mod, "_write_outputs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_mod, "load_callup_config", lambda *_: (_make_callup_config(callups_only_mode=False), {}))

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

    assert captured.get("builder_players") == ["freeagent", "signuphero"]


def test_callups_only_mode_limits_pool_to_signups(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2030-01-01-A", 1, "SignupHero", "Damage", 1]],
    )
    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [["SignupHero", 1], ["FreeAgent", 1]],
    )
    _write_csv(data_dir / "absences.csv", ["PlayerName", "From", "To", "InAlliance"], [])
    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment"],
        [["SignupHero", "A", "Start", "none"]],
    )
    _write_csv(data_dir / "event_responses_next.csv", ["PlayerName", "Status"], [])

    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(main_mod, "build_deterministic_roster", lambda df, **_: _fake_builder_capture(df, captured))
    monkeypatch.setattr(main_mod, "_write_outputs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_mod, "load_callup_config", lambda *_: (_make_callup_config(callups_only_mode=True), {}))

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

    assert captured.get("builder_players") == ["signuphero"]


def test_absent_players_are_excluded_from_roster(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_csv(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2030-01-01-A", 1, "Available", "Damage", 1], ["DS-2030-01-01-A", 2, "Unavailable", "Damage", 1]],
    )
    _write_csv(
        data_dir / "alliance.csv",
        ["PlayerName", "InAlliance"],
        [["Available", 1], ["Unavailable", 1]],
    )
    _write_csv(
        data_dir / "absences.csv",
        ["PlayerName", "From", "To", "InAlliance"],
        [["Unavailable", "2000-01-01", "2100-01-01", 1]],
    )
    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment"],
        [["Available", "A", "Start", "none"], ["Unavailable", "A", "Start", "none"]],
    )
    _write_csv(data_dir / "event_responses_next.csv", ["PlayerName", "Status"], [])

    captured: dict[str, list[str] | pd.DataFrame] = {}

    def _fake_builder(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        # mirror candidates to show who reached roster
        captured["builder_pool"] = sorted(df["PlayerName"].tolist())
        return pd.DataFrame({
            "PlayerName": df["PlayerName"],
            "Group": ["A"] * len(df),
            "Role": ["Start"] * len(df),
            "_selection_stage": ["test"] * len(df),
        })

    def _capture_outputs(_out_dir, roster_df: pd.DataFrame, _json_payload):
        captured["roster"] = roster_df

    monkeypatch.setattr(main_mod, "build_deterministic_roster", _fake_builder)
    monkeypatch.setattr(main_mod, "_write_outputs", _capture_outputs)

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

    assert captured.get("builder_pool") == ["available"]
    roster_df = captured.get("roster")
    assert roster_df is not None
    assert set(roster_df["PlayerName"].tolist()) == {"Available"}


def test_hard_commit_forced_into_roster_even_below_threshold():
    df = pd.DataFrame(
        {
            "PlayerName": ["hard_commit", "high_prob"],
            "attend_prob": [0.05, 0.95],
            "PrefGroup": ["A", "A"],
            "PrefMode": ["hard", "soft"],
            "PrefBoost": [0.0, 0.0],
            "risk_penalty": [0.0, 0.0],
        }
    )

    roster = utils_mod.build_deterministic_roster(
        df,
        forced_assignments=[{"PlayerName": "hard_commit", "Group": "A", "Role": "Start"}],
        capacities_by_group_role={"A": {"Start": 0, "Ersatz": 0}, "B": {"Start": 0, "Ersatz": 0}},
        min_attend_start={"A": 0.8, "B": 0.8},
        min_attend_sub=0.8,
        allow_unfilled=True,
    )

    assert roster["PlayerName"].tolist() == ["hard_commit"]
    assert roster["_selection_stage"].tolist() == ["forced"]
