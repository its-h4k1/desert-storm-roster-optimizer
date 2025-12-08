"""Minimal deterministic roster builder for hard signups.

The goal is to keep the roster-producing surface easy to read: we only consume
the hard signup list and return a simple A/B roster plus reserves without any
callup or EB-specific switches.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List

from src.config import get_config
from src.core_signups import Signup


@dataclass(frozen=True)
class RosterEntry:
    name: str
    role: str
    note: str
    tags: List[str]
    source: str


DEFAULT_CAPACITY = {
    "A": {"Start": 20, "Ersatz": 10},
    "B": {"Start": 20, "Ersatz": 10},
}


def _role_from_wish(role_wish: str) -> str:
    norm = (role_wish or "").strip().lower()
    if norm.startswith("ersatz") or norm == "sub":
        return "Ersatz"
    return "Start"


def _group_from_wish(group_wish: str) -> str:
    norm = (group_wish or "").strip().upper()
    return "B" if norm == "B" else "A"


def _to_entry(signup: Signup) -> RosterEntry:
    tags = ["hard"]
    if signup.note:
        tags.append("note")
    return RosterEntry(
        name=signup.name,
        role=_role_from_wish(signup.role_wish),
        note=signup.note,
        tags=tags,
        source=signup.source,
    )


def build_rosters_from_hard_signups(
    signups: List[Signup],
    config=None,
) -> Dict[str, List[RosterEntry]]:
    """Distribute hard signups into teams A/B and a reserve bench.

    The builder keeps the distribution simple and deterministic:
    - A signup with a group wish of ``B`` is placed in team B if capacity
      permits; all others default to team A first.
    - ``Role`` decides whether a player is counted as starter (``Start``) or
      substitute (``Ersatz``); if the requested slot is full the player is
      pushed into the reserves list.
    """

    cfg = config or get_config()
    _ = cfg  # currently unused but kept for signature stability

    capacities = {g: roles.copy() for g, roles in DEFAULT_CAPACITY.items()}
    team_a: List[RosterEntry] = []
    team_b: List[RosterEntry] = []
    reserves: List[RosterEntry] = []

    for signup in signups:
        entry = _to_entry(signup)
        target_group = _group_from_wish(signup.group_wish)
        target_role = entry.role
        cap = capacities[target_group][target_role]

        if cap > 0:
            capacities[target_group][target_role] -= 1
            if target_group == "A":
                team_a.append(entry)
            else:
                team_b.append(entry)
        else:
            reserves.append(entry)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "team_a": team_a,
        "team_b": team_b,
        "reserves": reserves,
        "capacity": capacities,
    }


__all__ = ["RosterEntry", "build_rosters_from_hard_signups", "DEFAULT_CAPACITY"]
