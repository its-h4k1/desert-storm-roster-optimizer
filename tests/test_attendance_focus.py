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
    expected_by_team = attendance.get("expected_by_team") or {}
    assert expected_by_team.get("A", {}).get("total", 0) >= 1.0
    assert attendance.get("recommendation", {}).get("code")
