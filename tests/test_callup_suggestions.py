from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from src import main as main_mod


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    content = ",".join(header) + "\n" + "\n".join(",".join(map(str, row)) for row in rows)
    path.write_text(content, encoding="utf-8")


def test_callup_suggestions_prioritize_available_candidates(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    players = [
        "StarterA",
        "StarterB",
        "CandGood",
        "CandLow",
        "CandDecline",
        "CandHard",
        "CandAbsent",
    ]

    events = []
    for idx, name in enumerate(players, start=1):
        attend_flag = 0 if name == "CandLow" else 1
        events.append(["DS-2030-01-01-A", idx, name, "Damage", attend_flag])
    events.append(["DS-2030-01-02-B", 1, "CandGood", "Damage", 1])
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
        ["PlayerName", "From", "To", "InAlliance"],
        [["CandAbsent", "2030-01-01", "2031-01-01", 1]],
    )

    _write_csv(
        data_dir / "event_responses_next.csv",
        ["PlayerName", "Status", "Source", "Note"],
        [["CandDecline", "decline", "manual", ""], ["CandLow", "no_response", "manual", ""]],
    )

    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment"],
        [["CandHard", "B", "Start", "hard"]],
    )

    captured: dict[str, object] = {}

    def _fake_builder(df: pd.DataFrame, forced_assignments, **kwargs) -> pd.DataFrame:
        captured["builder_pool"] = df.copy()
        return pd.DataFrame(
            [
                {"PlayerName": "startera", "Group": "A", "Role": "Start", "NoShowOverall": 0.0, "NoShowRolling": 0.0, "risk_penalty": 0.0},
                {"PlayerName": "starterb", "Group": "B", "Role": "Start", "NoShowOverall": 0.0, "NoShowRolling": 0.0, "risk_penalty": 0.0},
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
    suggestions = payload.get("callup_suggestions") or {}
    teams = suggestions.get("teams") or {}
    b_suggestions = teams.get("B", {}).get("suggestions", [])
    names = {item.get("canon") for item in b_suggestions}

    assert "candgood" in names
    assert "candlow" not in names  # no-response gefiltert
    assert "canddecline" not in names  # decline gefiltert
    assert "candhard" not in names  # hard commitment
    assert "candabsent" not in names  # aktive Abwesenheit

    assert all(item.get("attend_prob", 0) >= 0.5 for item in b_suggestions)
    assert b_suggestions and b_suggestions[0].get("reason", "").startswith("AttendProb")

