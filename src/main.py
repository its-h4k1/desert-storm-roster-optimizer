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
from datetime import timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.config import get_config
from src.attendance_config import RELIABILITY_START_DATE
from src.core_roster import RosterEntry, build_rosters_from_hard_signups
from src.core_signups import Signup, load_hard_signups_for_next_event
from src.effective_signups import (
    EffectiveSignupState,
    PlayerSignupState,
    compute_event_datetime_local,
    determine_effective_signup_states,
    signup_deadline_for_event,
)
from src.event_responses import EventResponse, load_event_responses_for_next_event
from src.stats import PlayerReliability, compute_player_reliability
from src.utils import canonical_name


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


def _load_event_history() -> pd.DataFrame:
    """Load historical DS event attendance CSVs for reliability stats."""

    if pd is None:
        return pd.DataFrame(
            columns=["EventID", "PlayerName", "RoleAtRegistration", "Teilgenommen"]
        )

    base = Path("data")
    pattern = "DS-*-*-*.csv"
    keep = []
    for path in base.glob(pattern):
        name = path.name
        if not name or not name.upper().startswith("DS-"):
            continue
        if len(name.split("-")) < 4:
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue

        if "EventID" not in df.columns:
            df["EventID"] = path.stem
        if "PlayerName" not in df.columns or "RoleAtRegistration" not in df.columns:
            continue
        if "Teilgenommen" not in df.columns:
            df["Teilgenommen"] = 0
        cols = [
            "EventID",
            "PlayerName",
            "RoleAtRegistration",
            "Teilgenommen",
        ]
        effective_col = None
        for cand in ["effective_signup_state", "EffectiveSignupState", "effective_state"]:
            if cand in df.columns:
                effective_col = cand
                break
        if effective_col:
            cols.append(effective_col)
        keep.append(df[cols].copy())

    if not keep:
        return pd.DataFrame(
            columns=["EventID", "PlayerName", "RoleAtRegistration", "Teilgenommen"]
        )
    return pd.concat(keep, ignore_index=True)


def _build_payload(
    *,
    signups: List[Signup],
    eligible_signups: List[Signup],
    responses: List[EventResponse],
    signup_states: Dict[str, PlayerSignupState],
    rosters: Dict[str, object],
    args: argparse.Namespace,
    event_datetime_local,
    signup_deadline_local,
    config,
    reliability_players: Dict[str, PlayerReliability] | None = None,
) -> Dict[str, object]:
    team_a: Dict[str, List[RosterEntry]] = rosters.get("team_a", {})  # type: ignore[assignment]
    team_b: Dict[str, List[RosterEntry]] = rosters.get("team_b", {})  # type: ignore[assignment]
    hard_signups_not_in_roster: List[RosterEntry] = rosters.get("hard_signups_not_in_roster", [])  # type: ignore[assignment]

    team_a_start = team_a.get("start", [])
    team_a_subs = team_a.get("subs", [])
    team_b_start = team_b.get("start", [])
    team_b_subs = team_b.get("subs", [])

    rostered_canons = {
        canonical_name(entry.name)
        for entry in [
            *team_a_start,
            *team_a_subs,
            *team_b_start,
            *team_b_subs,
        ]
    }
    hard_active_canons = {
        canon
        for canon, state in signup_states.items()
        if state.state == EffectiveSignupState.HARD_ACTIVE
    }
    hard_signups_not_in_roster = [
        entry
        for entry in hard_signups_not_in_roster
        if canonical_name(entry.name) in hard_active_canons
        and canonical_name(entry.name) not in rostered_canons
    ]

    name_by_canon: Dict[str, str] = {}
    for s in signups:
        name_by_canon[s.canon] = s.name
    for resp in responses:
        name_by_canon.setdefault(resp.canon, resp.name)

    signup_states_export: Dict[str, object] = {}
    for canon, state in signup_states.items():
        entry = {"state": state.state.value}
        if state.last_response and state.last_response.response_time:
            entry["last_response_time"] = (
                state.last_response.response_time.astimezone(timezone.utc).isoformat()
            )
        entry["canon"] = canon
        entry["name"] = name_by_canon.get(canon, canon)
        signup_states_export[name_by_canon.get(canon, canon)] = entry

    return {
        "event": {
            "id": args.event_id,
            "date": args.event_date,
            "time": args.event_time,
            "generated_at": rosters.get("generated_at"),
            "source": Path(args.event_signups).as_posix(),
            "event_datetime_local": event_datetime_local.isoformat(),
            "signup_deadline_local": signup_deadline_local.isoformat(),
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
            "hard_signups_eligible": len(eligible_signups),
            "responses": len(responses),
            "team_a_start": len(team_a_start),
            "team_a_subs": len(team_a_subs),
            "team_b_start": len(team_b_start),
            "team_b_subs": len(team_b_subs),
            "hard_signups_not_in_roster": len(hard_signups_not_in_roster),
        },
        "analysis": {
            "note": "Callups/EB/No-Show analyses intentionally decoupled from roster build.",
        },
        "signup_states": signup_states_export,
        "event_signups": {
            "hard_signups_only": config.HARD_SIGNUPS_ONLY,
            "hard_signups": len(signups),
            "hard_signups_eligible": len(eligible_signups),
            "responses": len(responses),
        },
        "reliability_config": {
            "reliability_start_date": (
                RELIABILITY_START_DATE.isoformat()
                if RELIABILITY_START_DATE is not None
                else None
            )
        },
        "reliability": {
            "players": {
                name: {
                    "events": stats.events,
                    "attendance": stats.attendance,
                    "no_shows": stats.no_shows,
                    "early_cancels": stats.early_cancels,
                    "late_cancels": stats.late_cancels,
                }
                for name, stats in (reliability_players or {}).items()
            },
            "meta": {
                "reliability_start_date": (
                    RELIABILITY_START_DATE.isoformat()
                    if RELIABILITY_START_DATE is not None
                    else None
                )
            },
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
    responses = load_event_responses_for_next_event()
    event_dt_local = compute_event_datetime_local(args.event_date, args.event_time)
    event_history = _load_event_history()
    reliability_players = compute_player_reliability(
        event_history, reliability_start_date=RELIABILITY_START_DATE
    )
    signup_states = determine_effective_signup_states(
        signups=signups,
        responses=responses,
        event_datetime_local=event_dt_local,
    )
    eligible_signups = [
        s
        for s in signups
        if signup_states.get(s.canon, PlayerSignupState(state=EffectiveSignupState.NONE)).state
        == EffectiveSignupState.HARD_ACTIVE
    ]
    rosters = build_rosters_from_hard_signups(eligible_signups, cfg)
    payload = _build_payload(
        signups=signups,
        eligible_signups=eligible_signups,
        responses=responses,
        signup_states=signup_states,
        rosters=rosters,
        args=args,
        event_datetime_local=event_dt_local,
        signup_deadline_local=signup_deadline_for_event(event_dt_local),
        config=cfg,
        reliability_players=reliability_players,
    )
    _write_outputs(Path(args.out), payload)
    print(
        f"[ok] roster built with {len(eligible_signups)} eligible hard signups (total {len(signups)}) → "
        f"A: {len(payload['team_a']['start'])} start / {len(payload['team_a']['subs'])} subs, "
        f"B: {len(payload['team_b']['start'])} start / {len(payload['team_b']['subs'])} subs, "
        f"not in roster: {len(payload['hard_signups_not_in_roster'])}"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
