"""Loader for callup recommendation thresholds.

Reads a YAML/JSON config file from ``data/callup_config.yml`` (or a
custom path) and falls back to embedded defaults if the file or fields
are missing. The resulting configuration is intentionally small so it
can be tuned without code changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml  # type: ignore


@dataclass(frozen=True)
class CallupConfig:
    version: int
    min_events: int
    low_n_max_events: int
    high_overall_threshold: float
    high_rolling_threshold: float
    rolling_uptick_min: float
    rolling_uptick_delta: float

    def to_snapshot(self) -> Dict[str, Any]:
        return asdict(self)


DEFAULT_CALLOUP_CONFIG = CallupConfig(
    version=1,
    min_events=3,
    low_n_max_events=2,
    high_overall_threshold=0.40,
    high_rolling_threshold=0.50,
    rolling_uptick_min=0.25,
    rolling_uptick_delta=0.10,
)


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_config_file(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    if path.suffix.lower() == ".json":
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def load_callup_config(path: str | Path = "data/callup_config.yml") -> Tuple[CallupConfig, Dict[str, Any]]:
    cfg_path = Path(path)
    defaults = DEFAULT_CALLOUP_CONFIG
    values = defaults.to_snapshot()
    meta: Dict[str, Any] = {
        "path": str(cfg_path),
        "loaded_from_file": False,
        "defaults_applied": [],
        "issues": [],
    }

    raw = _read_config_file(cfg_path)
    if raw is None:
        meta["issues"].append("config missing or unreadable; using defaults")
        meta["defaults_applied"] = list(values.keys())
        print(f"[warn] callup_config: {cfg_path} fehlt/fehlerhaft – nutze Defaults")
    else:
        meta["loaded_from_file"] = True
        for field in values.keys():
            if field not in raw:
                meta["defaults_applied"].append(field)
                continue
            if field in {"min_events", "low_n_max_events", "version"}:
                val = _coerce_int(raw.get(field), values[field])
            else:
                val = _coerce_float(raw.get(field), values[field])
            if val == values[field]:
                if raw.get(field) != values[field]:
                    meta["defaults_applied"].append(field)
            else:
                values[field] = val
        if meta["defaults_applied"]:
            missing = ", ".join(sorted(meta["defaults_applied"]))
            meta["issues"].append(f"Defaults für Felder verwendet: {missing}")
            print(
                f"[warn] callup_config: Felder fehlen/ungültig ({missing}) – Defaults verwendet"
            )
        print(
            f"[info] callup_config: verwende {cfg_path} (Version {values.get('version', defaults.version)})"
        )

    config = CallupConfig(**{k: values[k] for k in defaults.to_snapshot().keys()})
    return config, meta


__all__ = [
    "CallupConfig",
    "DEFAULT_CALLOUP_CONFIG",
    "load_callup_config",
]

