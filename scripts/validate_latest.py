from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def report_error(message: str) -> None:
    print(f"::error::{message}")


def report_notice(message: str) -> None:
    print(f"::notice::{message}")


def load_latest(path: Path) -> tuple[dict[str, Any] | None, bool]:
    if not path.exists():
        report_error("out/latest.json not found")
        return None, False

    try:
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except json.JSONDecodeError as exc:
        report_error(f"latest.json is not valid JSON (line {exc.lineno}, column {exc.colno})")
        return None, False
    except OSError as exc:
        report_error(f"could not read latest.json: {exc.strerror or exc}")
        return None, False

    if not isinstance(data, dict):
        report_error("latest.json must contain a JSON object")
        return None, False

    return data, True


def validate_players(players: Any) -> bool:
    if not isinstance(players, list):
        report_error(".players must be an array")
        return False
    if len(players) == 0:
        report_error(".players must contain at least one entry")
        return False

    missing_fields = []
    for index, player in enumerate(players):
        if not isinstance(player, dict):
            report_error(f".players[{index}] must be an object")
            return False
        for field in ("events_seen", "noshow_count"):
            if field not in player:
                missing_fields.append((index, field))

    for index, field in missing_fields:
        report_error(f".players[{index}] is missing '{field}'")

    return not missing_fields


def validate_schema(schema: Any, players: list[dict[str, Any]]) -> bool:
    if not isinstance(schema, dict):
        report_error(".schema must be an object")
        return False

    version = schema.get("version")
    if version != 2:
        report_error(".schema.version must equal 2")
        return False

    eb = schema.get("eb")
    if isinstance(eb, dict) and eb.get("enabled"):
        eligible = False
        for index, player in enumerate(players):
            eb_data = player.get("eb") if isinstance(player, dict) else None
            if isinstance(eb_data, dict) and "p_hat" in eb_data:
                eligible = True
                break
        if not eligible:
            report_error(".schema.eb.enabled requires at least one player with eb.p_hat")
            return False

    return True


def main() -> int:
    latest_path = Path("out/latest.json")
    data, ok = load_latest(latest_path)
    if not ok or data is None:
        return 1

    players = data.get("players")
    if not validate_players(players):
        return 1

    schema = data.get("schema")
    if not validate_schema(schema, players):
        return 1

    report_notice("latest.json validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
