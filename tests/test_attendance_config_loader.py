import sys

from src import main as main_mod
from src.attendance_config import DEFAULT_ATTENDANCE_CONFIG, load_attendance_config


def test_attendance_config_reads_overrides(tmp_path):
    cfg_path = tmp_path / "attendance_config.yml"
    cfg_path.write_text(
        """
attendance:
  min_start_A: 0.7
  target_expected_A:
    low: 10
    high: 12
  high_reliability_balance_ratio: 2.1
""",
        encoding="utf-8",
    )

    cfg, meta = load_attendance_config(cfg_path)

    assert cfg.min_start_A == 0.7
    assert cfg.target_expected_A.low == 10
    assert cfg.target_expected_A.high == 12
    assert cfg.high_reliability_balance_ratio == 2.1
    assert meta["loaded_from_file"] is True
    # Nicht gesetzte Felder fallen auf Defaults zurück
    assert "min_bench_B" in meta["defaults_applied"]
    assert cfg.min_bench_B == DEFAULT_ATTENDANCE_CONFIG.min_bench_B


def test_builder_includes_custom_attendance_snapshot(monkeypatch, tmp_path):
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
  min_start_A: 0.77
  min_start_B: 0.66
  min_bench_A: 0.53
  min_bench_B: 0.44
  target_expected_A:
    low: 21
    high: 27
  target_expected_B:
    low: 22
    high: 26
  hard_commit_floor: 0.91
  no_response_multiplier: 0.61
  high_reliability_balance_ratio: 1.9
"""
    (data_dir / "attendance_config.yml").write_text(cfg_text, encoding="utf-8")

    _write(
        data_dir / "events.csv",
        ["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"],
        [["DS-2030-01-01-A", 1, "Hero", "Damage", 1], ["DS-2030-01-01-A", 2, "Risky", "Damage", 0]],
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

    captured = {}

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
    attendance_snapshot = (payload.get("attendance") or {}).get("config_snapshot") or {}

    assert attendance_snapshot.get("min_start_A") == 0.77
    assert attendance_snapshot.get("min_start_B") == 0.66
    assert attendance_snapshot.get("hard_commit_floor") == 0.91
    assert attendance_snapshot.get("target_expected_A", {}).get("low") == 21
    assert attendance_snapshot.get("target_expected_B", {}).get("high") == 26
    assert attendance_snapshot.get("high_reliability_balance_ratio") == 1.9
