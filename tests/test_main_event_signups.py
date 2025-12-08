from pathlib import Path
import json
import sys

from src.core_signups import load_hard_signups_for_next_event
from src import main as main_mod


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    content = ",".join(header) + "\n" + "\n".join(",".join(map(str, row)) for row in rows)
    path.write_text(content, encoding="utf-8")


def test_load_hard_signups_filters_and_deduplicates(tmp_path):
    csv_path = tmp_path / "event_signups_next.csv"
    _write_csv(
        csv_path,
        ["PlayerName", "Group", "Role", "Commitment", "Source", "Note"],
        [
            ["Alpha", "A", "Start", "hard", "manual", ""],
            ["alpha", "A", "Start", "hard", "manual", "duplicate"],
            ["Bravo", "B", "Ersatz", "none", "manual", ""],
        ],
    )

    signups = load_hard_signups_for_next_event(str(csv_path))
    assert len(signups) == 1
    assert signups[0].name == "Alpha"
    assert signups[0].group_wish == "A"
    assert signups[0].role_wish == "Start"
    assert signups[0].commitment == "hard"


def test_main_builds_simple_roster(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    _write_csv(
        data_dir / "event_signups_next.csv",
        ["PlayerName", "Group", "Role", "Commitment", "Source", "Note"],
        [
            ["Alpha", "A", "Start", "hard", "manual", ""],
            ["Bravo", "B", "Ersatz", "hard", "manual", ""],
            ["Charlie", "B", "Ersatz", "hard", "manual", "Late"],
        ],
    )

    argv = [
        "prog",
        "--event-signups",
        "data/event_signups_next.csv",
        "--out",
        "out",
        "--event-id",
        "DS-TEST",
        "--event-date",
        "2024-12-01",
        "--event-time",
        "20:00",
    ]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    main_mod.main()

    latest = json.loads((tmp_path / "out/latest.json").read_text(encoding="utf-8"))
    docs_latest = json.loads((tmp_path / "docs/out/latest.json").read_text(encoding="utf-8"))
    assert latest == docs_latest

    assert latest["event"]["id"] == "DS-TEST"
    assert latest["event"]["date"] == "2024-12-01"
    assert latest["event"]["time"] == "20:00"

    assert len(latest["team_a"]) == 1
    assert len(latest["team_b"]) == 2
    assert latest["reserves"] == []

    alpha = latest["team_a"][0]
    assert alpha["name"] == "Alpha"
    assert alpha["role"] == "Start"

    stats = latest["signup_stats"]
    assert stats["hard_signups"] == 3
    assert stats["team_a"] == 1
    assert stats["team_b"] == 2
    assert stats["reserves"] == 0
