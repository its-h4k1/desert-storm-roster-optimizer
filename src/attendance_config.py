"""Attendance configuration for the roster builder.

All attendance-related thresholds live here to avoid scattered magic numbers.
Values are read from ``data/attendance_config.yml`` (if present) and fall back
onto the defaults documented below.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml  # type: ignore


@dataclass(frozen=True)
class AttendanceBand:
    low: float
    high: float

    def to_snapshot(self) -> Dict[str, float]:
        return {"low": float(self.low), "high": float(self.high)}


@dataclass(frozen=True)
class AttendanceConfig:
    min_start_A: float
    min_start_B: float
    min_bench_A: float
    min_bench_B: float
    target_expected_A: AttendanceBand
    target_expected_B: AttendanceBand
    hard_commit_floor: float
    no_response_multiplier: float
    high_reliability_balance_ratio: float

    def min_start_thresholds(self) -> Dict[str, float]:
        return {"A": float(self.min_start_A), "B": float(self.min_start_B)}

    def min_bench_thresholds(self) -> Dict[str, float]:
        return {"A": float(self.min_bench_A), "B": float(self.min_bench_B)}

    def target_expected(self) -> Dict[str, Dict[str, float]]:
        return {
            "A": self.target_expected_A.to_snapshot(),
            "B": self.target_expected_B.to_snapshot(),
        }

    def to_snapshot(self) -> Dict[str, Any]:
        return {
            "min_start_A": float(self.min_start_A),
            "min_start_B": float(self.min_start_B),
            "min_bench_A": float(self.min_bench_A),
            "min_bench_B": float(self.min_bench_B),
            "target_expected_A": self.target_expected_A.to_snapshot(),
            "target_expected_B": self.target_expected_B.to_snapshot(),
            "hard_commit_floor": float(self.hard_commit_floor),
            "no_response_multiplier": float(self.no_response_multiplier),
            "high_reliability_balance_ratio": float(
                self.high_reliability_balance_ratio
            ),
        }


DEFAULT_ATTENDANCE_CONFIG = AttendanceConfig(
    min_start_A=0.55,
    min_start_B=0.55,
    min_bench_A=0.45,
    min_bench_B=0.45,
    target_expected_A=AttendanceBand(low=24.0, high=28.0),
    target_expected_B=AttendanceBand(low=24.0, high=28.0),
    hard_commit_floor=0.92,
    no_response_multiplier=0.65,
    high_reliability_balance_ratio=1.8,
)


def _coerce_float(value: Any, default: float) -> float:
    if isinstance(value, bool) or value is None:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _read_yaml(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def load_attendance_config(
    path: str | Path = "data/attendance_config.yml",
) -> Tuple[AttendanceConfig, Dict[str, Any]]:
    cfg_path = Path(path)
    defaults = DEFAULT_ATTENDANCE_CONFIG
    values = defaults.to_snapshot()
    meta: Dict[str, Any] = {
        "path": str(cfg_path),
        "loaded_from_file": False,
        "defaults_applied": [],
        "issues": [],
    }

    raw = _read_yaml(cfg_path) or {}
    attendance_block = raw.get("attendance", raw)
    if not attendance_block:
        meta["issues"].append("attendance config missing or empty; using defaults")
        meta["defaults_applied"] = list(values.keys())
        print(
            f"[warn] attendance_config: {cfg_path} fehlt/leer – verwende eingebettete Defaults"
        )
    else:
        meta["loaded_from_file"] = True
        for key, default_val in values.items():
            if key not in attendance_block:
                meta["defaults_applied"].append(key)
                continue
            if key.startswith("target_expected_"):
                band_val = attendance_block.get(key, {}) or {}
                low = _coerce_float(band_val.get("low"), default_val.get("low", 0.0))
                high = _coerce_float(band_val.get("high"), default_val.get("high", 0.0))
                values[key] = {"low": low, "high": high}
                if band_val.get("low") != low or band_val.get("high") != high:
                    meta["defaults_applied"].append(key)
                continue
            coerced = _coerce_float(attendance_block.get(key), default_val)
            if attendance_block.get(key) != coerced:
                meta["defaults_applied"].append(key)
            values[key] = coerced
        if meta["defaults_applied"]:
            missing = ", ".join(sorted(meta["defaults_applied"]))
            meta["issues"].append(f"Defaults für Felder verwendet: {missing}")
            print(
                "[warn] attendance_config: Felder fehlen/ungültig "
                f"({missing}) – Defaults verwendet"
            )
        print(
            f"[info] attendance_config: verwende {cfg_path} ({'Block attendance' if 'attendance' in raw else 'flat schema'})"
        )

    config = AttendanceConfig(
        min_start_A=float(values["min_start_A"]),
        min_start_B=float(values["min_start_B"]),
        min_bench_A=float(values["min_bench_A"]),
        min_bench_B=float(values["min_bench_B"]),
        target_expected_A=AttendanceBand(
            low=float(values["target_expected_A"]["low"]),
            high=float(values["target_expected_A"]["high"]),
        ),
        target_expected_B=AttendanceBand(
            low=float(values["target_expected_B"]["low"]),
            high=float(values["target_expected_B"]["high"]),
        ),
        hard_commit_floor=float(values["hard_commit_floor"]),
        no_response_multiplier=float(values["no_response_multiplier"]),
        high_reliability_balance_ratio=float(values["high_reliability_balance_ratio"]),
    )
    return config, meta


__all__ = [
    "AttendanceBand",
    "AttendanceConfig",
    "DEFAULT_ATTENDANCE_CONFIG",
    "load_attendance_config",
]
