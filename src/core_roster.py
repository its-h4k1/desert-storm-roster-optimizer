"""Minimal deterministic roster builder for hard signups.

The goal is to keep the roster-producing surface easy to read: we only consume
the hard signup list and return a simple A/B roster with explicit start/sub
splits. Any overflow is tracked separately so the matchday view can clearly
show which hard signups are not part of the roster.
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
) -> Dict[str, object]:
    """Distribute hard signups into teams A/B with separate start/sub lists.

    The builder keeps the distribution simple and deterministic:
    - A signup with a group wish of ``B`` is placed in team B if capacity
      permits; all others default to team A first.
    - ``Role`` decides whether a player is counted as starter (``Start``) or
      substitute (``Ersatz``); if the requested slot is full the player is
      tracked in ``hard_signups_not_in_roster``.
    """

    cfg = config or get_config()
    _ = cfg  # currently unused but kept for signature stability

    capacities = {g: roles.copy() for g, roles in DEFAULT_CAPACITY.items()}
    team_a: Dict[str, List[RosterEntry]] = {"start": [], "subs": []}
    team_b: Dict[str, List[RosterEntry]] = {"start": [], "subs": []}
    hard_signups_not_in_roster: List[RosterEntry] = []

    for signup in signups:
        entry = _to_entry(signup)
        target_group = _group_from_wish(signup.group_wish)
        target_role = entry.role
        cap = capacities[target_group][target_role]

        if cap > 0:
            capacities[target_group][target_role] -= 1
            slot = "start" if target_role == "Start" else "subs"
            if target_group == "A":
                team_a[slot].append(entry)
            else:
                team_b[slot].append(entry)
        else:
            hard_signups_not_in_roster.append(entry)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "team_a": team_a,
        "team_b": team_b,
        "hard_signups_not_in_roster": hard_signups_not_in_roster,
        "capacity": capacities,
    }


__all__ = ["RosterEntry", "build_rosters_from_hard_signups", "DEFAULT_CAPACITY"]
