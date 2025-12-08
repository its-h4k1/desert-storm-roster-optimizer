"""Minimal hard-signup loader for the next Desert Storm event.

This module deliberately keeps the surface area tiny: it only knows how to
read ``data/event_signups_next.csv`` (or a caller-provided path) and returns a
list of normalized hard signups without pulling in alliance data, absences or
callup overlays.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import pandas as pd

from src.utils import canonical_name


@dataclass(frozen=True)
class Signup:
    """A single signup row from ``event_signups_next.csv``.

    Attributes:
        name: Display name as provided in the CSV.
        canon: Normalized name used for deduplication.
        group_wish: Desired team (``A`` / ``B`` / ``""`` for no preference).
        role_wish: Desired role (``Start`` / ``Ersatz`` / ``""``).
        commitment: Commitment string; only ``hard`` rows are returned by the
            loader but the attribute is kept for clarity.
        source: Informational source label (e.g. ``ingame``, ``manual``).
        note: Free-form note supplied by the caller.
    """

    name: str
    canon: str
    group_wish: str
    role_wish: str
    commitment: str
    source: str
    note: str


def _normalize_commitment(value: str) -> str:
    norm = (value or "").strip().lower()
    return "hard" if norm == "hard" else "none"


def load_hard_signups_for_next_event(path: str = "data/event_signups_next.csv") -> List[Signup]:
    """Load and normalize hard signups for the upcoming event.

    Only rows with ``Commitment = hard`` are returned. Column names are treated
    case-insensitively to make spreadsheet exports more forgiving.
    """

    csv_path = Path(path)
    cols = ["PlayerName", "Group", "Role", "Commitment", "Source", "Note"]
    if not csv_path.exists():
        return []

    df = pd.read_csv(csv_path, dtype=str)

    # Map lowercase headers back to the expected casing if necessary.
    lower_to_expected = {c.lower(): c for c in cols}
    for col in list(df.columns):
        key = str(col).strip().lower()
        if key in lower_to_expected and lower_to_expected[key] not in df.columns:
            df = df.rename(columns={col: lower_to_expected[key]})

    for col in cols:
        if col not in df.columns:
            df[col] = ""

    df = df[cols].copy()
    df["PlayerName"] = df["PlayerName"].fillna("").astype(str).str.strip()
    df = df[df["PlayerName"] != ""]

    df["Commitment"] = df["Commitment"].map(_normalize_commitment)
    df = df[df["Commitment"] == "hard"]

    df["canon"] = df["PlayerName"].map(canonical_name)
    df["Group"] = df["Group"].fillna("").astype(str).str.strip().str.upper()
    df["Role"] = df["Role"].fillna("").astype(str).str.strip().str.title()
    df["Source"] = df["Source"].fillna("manual").astype(str).str.strip().replace("", "manual")
    df["Note"] = df["Note"].fillna("").astype(str)

    signups: List[Signup] = []
    seen: set[str] = set()
    for row in df.itertuples(index=False):
        canon = getattr(row, "canon")
        if not canon or canon in seen:
            continue
        seen.add(canon)
        signups.append(
            Signup(
                name=getattr(row, "PlayerName"),
                canon=canon,
                group_wish=getattr(row, "Group"),
                role_wish=getattr(row, "Role"),
                commitment=getattr(row, "Commitment"),
                source=getattr(row, "Source"),
                note=getattr(row, "Note"),
            )
        )

    return signups


__all__ = ["Signup", "load_hard_signups_for_next_event"]
