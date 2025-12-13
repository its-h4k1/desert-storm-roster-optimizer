"""Convert legacy DS A/B CSV results into unified JSON payloads.

Usage:
    python scripts/migrate_event_results.py --event-date 2025-12-05

The script reads `data/DS-YYYY-MM-DD-A.csv` / `-B.csv`, normalizes player
names using the alias resolver and writes the combined payload to
`data/event_results/DS-YYYY-MM-DD.json` and mirrors it to
`docs/data/event_results/DS-YYYY-MM-DD.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils import canonical_name, load_alias_map


EVENT_PREFIX = "DS"


def _base_event_id(event_date: str) -> str:
    return f"{EVENT_PREFIX}-{event_date}"


def _strip_group_suffix(event_id: str) -> Tuple[str, str | None]:
    parts = event_id.rsplit("-", 1)
    if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha():
        return parts[0], parts[1].upper()
    return event_id, None


def _load_alias_map(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        return load_alias_map(path.as_posix())
    except Exception:
        return {}


def _iter_source_files(event_id_base: str, data_dir: Path) -> Iterable[Tuple[str, Path]]:
    for group in ["A", "B"]:
        path = data_dir / f"{event_id_base}-{group}.csv"
        if path.exists():
            yield group, path


def _load_results_from_csv(path: Path, group_hint: str | None, alias_map: Dict[str, str]) -> List[Dict[str, object]]:
    df = pd.read_csv(path)
    results: List[Dict[str, object]] = []

    for _, row in df.iterrows():
        event_id_raw = str(row.get("EventID", path.stem)).strip()
        base_event_id, group_from_id = _strip_group_suffix(event_id_raw)
        group = group_from_id or group_hint or ""

        raw_name = str(row.get("PlayerName", "")).strip()
        canon = canonical_name(raw_name)
        player_key = alias_map.get(canon, canon)

        role = str(row.get("RoleAtRegistration", row.get("Role", ""))).strip()
        slot_raw = row.get("Slot", "")
        slot = role or str(slot_raw).strip()

        attended_raw = row.get("Teilgenommen", row.get("attended"))
        try:
            attended = bool(int(attended_raw))
        except Exception:
            attended = bool(attended_raw)

        points_raw = row.get("Punkte", row.get("points", 0))
        try:
            points = int(float(points_raw))
        except Exception:
            points = 0

        note = str(row.get("Warnungen", row.get("note", ""))).replace("\n", "; ").strip()

        results.append(
            {
                "event_id": base_event_id,
                "player_key": player_key,
                "display_name_snapshot": raw_name or player_key,
                "slot": slot or role,
                "group": group,
                "role": role,
                "attended": attended,
                "points": points,
                "note": note,
            }
        )

    return results


def migrate_event(event_date: str, data_dir: Path, docs_dir: Path, alias_map: Dict[str, str]) -> Dict[str, object]:
    event_id_base = _base_event_id(event_date)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    all_results: List[Dict[str, object]] = []

    for group, path in _iter_source_files(event_id_base, data_dir):
        all_results.extend(_load_results_from_csv(path, group, alias_map))

    payload = {
        "event_id": event_id_base,
        "generated_at": generated_at,
        "results": all_results,
    }

    out_path = data_dir / "event_results" / f"{event_id_base}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    mirror_path = docs_dir / "event_results" / f"{event_id_base}.json"
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    mirror_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Migrate DS CSV event results into JSON")
    ap.add_argument("--event-date", required=True, help="Date component YYYY-MM-DD (without DS- prefix)")
    ap.add_argument("--data-dir", default="data", help="Directory containing DS-*-A/B.csv files")
    ap.add_argument("--docs-dir", default="docs/data", help="Directory to mirror event_results payloads")
    ap.add_argument("--aliases", default="data/aliases.csv", help="Optional alias table")

    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    docs_dir = Path(args.docs_dir)
    alias_map = _load_alias_map(Path(args.aliases))

    payload = migrate_event(args.event_date, data_dir, docs_dir, alias_map)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
