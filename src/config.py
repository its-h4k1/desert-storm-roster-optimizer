"""Runtime configuration loader for the roster optimizer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class Config:
    EB_ENABLE: bool
    EB_N0: float
    EB_LAMBDA: float
    START_NO_DATA_CAP: int
    WINSORIZE: bool
    PRIOR_FALLBACK: float
    PRIOR_PAD: float
    HARD_SIGNUPS_ONLY: bool


DEFAULTS: Dict[str, Any] = {
    "EB_ENABLE": True,
    "EB_N0": 4.0,
    "EB_LAMBDA": 0.2,
    "START_NO_DATA_CAP": 2,
    "WINSORIZE": True,
    "PRIOR_FALLBACK": 0.18,
    "PRIOR_PAD": 0.02,
    "HARD_SIGNUPS_ONLY": False,
}

_CONFIG_CACHE: Config | None = None


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if s in {"0", "false", "f", "no", "n", "off", ""}:
            return False
    return default


def _coerce_numeric(value: Any, default: float, *, as_int: bool = False) -> float | int:
    if value is None:
        return int(default) if as_int else float(default)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value) if as_int else float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return int(default) if as_int else float(default)
        try:
            num = float(s)
        except ValueError:
            return int(default) if as_int else float(default)
        return int(num) if as_int else float(num)
    return int(default) if as_int else float(default)


def _normalize_value(key: str, value: Any, defaults: Dict[str, Any]) -> Any:
    default = defaults[key]
    if isinstance(default, bool):
        return _coerce_bool(value, default)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(_coerce_numeric(value, default, as_int=True))
    if isinstance(default, float):
        return float(_coerce_numeric(value, default))
    return value if value is not None else default


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).upper(): v for k, v in data.items()}


def get_config() -> Config:
    """Load configuration with precedence: ENV > roster.yml > defaults."""

    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    values: Dict[str, Any] = dict(DEFAULTS)

    yaml_values = _read_yaml(Path("roster.yml"))
    for key, val in yaml_values.items():
        if key in values:
            values[key] = _normalize_value(key, val, DEFAULTS)

    for key in list(values.keys()):
        env_val = os.getenv(key)
        if env_val is not None:
            values[key] = _normalize_value(key, env_val, DEFAULTS)

    cfg = Config(
        EB_ENABLE=bool(values["EB_ENABLE"]),
        EB_N0=float(values["EB_N0"]),
        EB_LAMBDA=float(values["EB_LAMBDA"]),
        START_NO_DATA_CAP=int(values["START_NO_DATA_CAP"]),
        WINSORIZE=bool(values["WINSORIZE"]),
        PRIOR_FALLBACK=float(values["PRIOR_FALLBACK"]),
        PRIOR_PAD=float(values["PRIOR_PAD"]),
        HARD_SIGNUPS_ONLY=bool(values["HARD_SIGNUPS_ONLY"]),
    )

    _CONFIG_CACHE = cfg
    return cfg


__all__ = ["Config", "get_config"]

