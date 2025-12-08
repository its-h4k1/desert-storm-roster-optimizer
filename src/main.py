# -*- coding: utf-8 -*-
"""Entry point for building the next Desert Storm roster.

This edition keeps the core flow intentionally small:
1. Load hard commitments from ``data/event_signups_next.csv`` via
   :func:`src.core_signups.load_hard_signups_for_next_event`.
2. Build deterministic Team A/B line-ups with explicit start/sub splits via
   :func:`src.core_roster.build_rosters_from_hard_signups`.
3. Emit a slim JSON payload that powers the matchday view.

Analysis helpers (callups, EB/no-show statistics) can hook into the exported
payload but no longer steer the core roster build.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from src.config import get_config
from src.core_roster import RosterEntry, build_rosters_from_hard_signups
from src.core_signups import Signup, load_hard_signups_for_next_event


# --------------------------
# CLI
# --------------------------

def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build a minimal hard-commit roster")
    ap.add_argument(
        "--event-signups",
        default="data/event_signups_next.csv",
        help="CSV with PlayerName,Group,Role,Commitment,Source,Note",
    )
    ap.add_argument(
        "--out",
        default="out",
        help="Output directory for latest.json (docs/out is mirrored automatically)",
    )
    ap.add_argument(
        "--event-id",
        default="DS-NEXT",
        help="Identifier for the upcoming event (optional metadata)",
    )
    ap.add_argument(
        "--event-date",
        default="",
        help="Optional ISO date for the upcoming event",
    )
    ap.add_argument(
        "--event-time",
        default="",
        help="Optional local time for the upcoming event",
    )
    return ap.parse_args()


# --------------------------
# Payload helpers
# --------------------------

def _entry_to_dict(entry: RosterEntry) -> Dict[str, object]:
    return {
        "name": entry.name,
        "role": entry.role,
        "note": entry.note,
        "tags": entry.tags,
        "source": entry.source,
    }


def _build_payload(
    *,
    signups: List[Signup],
    rosters: Dict[str, object],
    args: argparse.Namespace,
) -> Dict[str, object]:
    team_a: Dict[str, List[RosterEntry]] = rosters.get("team_a", {})  # type: ignore[assignment]
    team_b: Dict[str, List[RosterEntry]] = rosters.get("team_b", {})  # type: ignore[assignment]
    hard_signups_not_in_roster: List[RosterEntry] = rosters.get("hard_signups_not_in_roster", [])  # type: ignore[assignment]

    team_a_start = team_a.get("start", [])
    team_a_subs = team_a.get("subs", [])
    team_b_start = team_b.get("start", [])
    team_b_subs = team_b.get("subs", [])

    return {
        "event": {
            "id": args.event_id,
            "date": args.event_date,
            "time": args.event_time,
            "generated_at": rosters.get("generated_at"),
            "source": Path(args.event_signups).as_posix(),
        },
        "team_a": {
            "start": [_entry_to_dict(e) for e in team_a_start],
            "subs": [_entry_to_dict(e) for e in team_a_subs],
        },
        "team_b": {
            "start": [_entry_to_dict(e) for e in team_b_start],
            "subs": [_entry_to_dict(e) for e in team_b_subs],
        },
        "hard_signups_not_in_roster": [
            _entry_to_dict(e) for e in hard_signups_not_in_roster
        ],
        "signup_stats": {
            "hard_signups": len(signups),
            "team_a_start": len(team_a_start),
            "team_a_subs": len(team_a_subs),
            "team_b_start": len(team_b_start),
            "team_b_subs": len(team_b_subs),
            "hard_signups_not_in_roster": len(hard_signups_not_in_roster),
        },
        "analysis": {
            "note": "Callups/EB/No-Show analyses intentionally decoupled from roster build.",
        },
    }


def _write_outputs(out_dir: Path, payload: Dict[str, object]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    docs_out = Path("docs/out")
    docs_out.mkdir(parents=True, exist_ok=True)

    json_str = json.dumps(payload, ensure_ascii=False, indent=2)
    (out_dir / "latest.json").write_text(json_str, encoding="utf-8")
    (docs_out / "latest.json").write_text(json_str, encoding="utf-8")


# --------------------------
# Main
# --------------------------

def main() -> None:
    args = _parse_args()
    cfg = get_config()
    signups = load_hard_signups_for_next_event(args.event_signups)
    rosters = build_rosters_from_hard_signups(signups, cfg)
    payload = _build_payload(signups=signups, rosters=rosters, args=args)
    _write_outputs(Path(args.out), payload)
    print(
        f"[ok] roster built with {len(signups)} hard signups → "
        f"A: {len(payload['team_a']['start'])} start / {len(payload['team_a']['subs'])} subs, "
        f"B: {len(payload['team_b']['start'])} start / {len(payload['team_b']['subs'])} subs, "
        f"not in roster: {len(payload['hard_signups_not_in_roster'])}"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
