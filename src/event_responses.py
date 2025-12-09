"""Loader for event responses (cancellations / no replies) for the next event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pandas as pd

from src.utils import canonical_name


@dataclass(frozen=True)
class EventResponse:
    name: str
    canon: str
    status: str
    response_time: datetime | None
    note: str
    source: str


_RESPONSE_STATUS_ALIASES = {
    "decline": "cancelled",
    "declined": "cancelled",
    "absage": "cancelled",
    "cancel": "cancelled",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "no": "cancelled",
    "no_response": "no_response",
    "none": "no_response",
    "unanswered": "no_response",
    "missing": "no_response",
    "unknown": "no_response",
    "maybe": "maybe",
}


def _normalize_response_status(value: str) -> str:
    norm = (value or "").strip().lower()
    return _RESPONSE_STATUS_ALIASES.get(norm, "")


def _parse_response_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
    except Exception:
        return None
    if ts is None or ts is pd.NaT or pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize(timezone.utc)
    return ts.to_pydatetime()


def load_event_responses_for_next_event(path: str = "data/event_responses_next.csv") -> List[EventResponse]:
    """Load responses for the next event.

    The loader keeps the structure intentionally slim and focuses on the
    cancellation/no-response layer for the upcoming roster build.
    """

    csv_path = Path(path)
    cols = ["PlayerName", "Status", "ResponseTime", "Source", "Note"]
    if not csv_path.exists():
        return []

    df = pd.read_csv(csv_path, dtype=str)

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

    df["canon"] = df["PlayerName"].map(canonical_name)
    df["Status"] = df["Status"].map(_normalize_response_status)
    df = df[df["Status"] != ""]
    df["ResponseTime"] = df["ResponseTime"].fillna("").astype(str)
    df["Source"] = df["Source"].fillna("manual").astype(str).str.strip().replace("", "manual")
    df["Note"] = df["Note"].fillna("").astype(str)

    responses: List[EventResponse] = []
    for row in df.itertuples(index=False):
        canon = getattr(row, "canon", "")
        if not canon:
            continue
        responses.append(
            EventResponse(
                name=getattr(row, "PlayerName"),
                canon=canon,
                status=getattr(row, "Status"),
                response_time=_parse_response_time(getattr(row, "ResponseTime", "")),
                note=getattr(row, "Note"),
                source=getattr(row, "Source"),
            )
        )

    return responses


__all__ = ["EventResponse", "load_event_responses_for_next_event"]
