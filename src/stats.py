# -*- coding: utf-8 -*-
"""
stats.py – Teilnahme-Metriken & Wahrscheinlichkeiten aus Event-Historie.

Kernideen
- Namen werden deterministisch kanonisiert (src.utils.canonical_name).
- Optional: Alias-Mapping zusammenführen (z. B. "DarkSchredder" → "DarkWerwolf").
- Gewichtet mit exponentiellem Zerfall (Halbwertszeit konfigurierbar).
- Liefert:
  * compute_role_probs(...)  → p_start / p_sub + Rollen-Metriken pro Spieler
  * compute_player_history(...) → rollenübergreifende Metriken pro Spieler

Erwartetes Events-Schema (mindestens):
  EventID, PlayerName, RoleAtRegistration, Teilgenommen
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, List, Mapping

from datetime import date, datetime, timezone
import re
import math

import pandas as pd

# Paket-Import (aus utils.py)
from src.config import get_config
from src.utils import parse_event_date, exp_decay_weight, canonical_name
from src.effective_signups import EffectiveSignupState


def _load_reliability_start_date() -> tuple[str | None, date | None]:
    cfg = get_config()
    start_date = getattr(cfg, "RELIABILITY_START_DATE", None)
    raw: str | None = None
    parsed: date | None = None

    if isinstance(start_date, date):
        raw = start_date.isoformat()
        parsed = start_date
    elif isinstance(start_date, str):
        raw = start_date.strip() or None
        if raw:
            try:
                parsed = date.fromisoformat(raw)
            except ValueError:
                parsed = None

    return raw, parsed


RELIABILITY_START_DATE_RAW, RELIABILITY_START_DATE = _load_reliability_start_date()

ROLES_START = {"Start"}
ROLES_SUB = {"Ersatz"}

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
_GROUP_RE = re.compile(r"^DS-\d{4}-\d{2}-\d{2}-([A-Z])$", re.IGNORECASE)


def _extract_group(event_id: str) -> str:
    """Gibt 'A'/'B' (oder '') aus einer EventID wie DS-YYYY-MM-DD-A zurück."""
    s = str(event_id).strip()
    m = _GROUP_RE.match(s)
    return m.group(1).upper() if m else ""


def _apply_alias_and_canon(name: str, alias_map: Optional[Dict[str, str]]) -> str:
    """
    Wendet zuerst canonical_name an und dann (falls vorhanden) ein Alias-Mapping.
    alias_map muss mit bereits kanonisierten keys/values befüllt sein (s. prepare_alias_map).
    """
    c = canonical_name(name)
    if alias_map:
        return alias_map.get(c, c)
    return c


def prepare_alias_map(raw_map: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """
    Nimmt ein beliebiges Mapping alter→neuer Namen und kanonisiert beide Seiten.
    Gibt ein neues Dict zurück, das in _apply_alias_and_canon direkt verwendbar ist.
    """
    if not raw_map:
        return None
    out: Dict[str, str] = {}
    for k, v in raw_map.items():
        ck = canonical_name(k)
        cv = canonical_name(v)
        if ck and cv:
            out[ck] = cv
    return out


# ------------------------------------------------------------
# Vorverarbeitung & Aggregationsbausteine
# ------------------------------------------------------------
def _prep(
    events: pd.DataFrame,
    *,
    alias_map: Optional[Dict[str, str]] = None,
    prepared_alias_map: Optional[Dict[str, str]] = None,
    half_life_days: float = 90.0,
    reference_dt: Optional[datetime] = None,
    reliability_start_date: date | None = RELIABILITY_START_DATE,
) -> pd.DataFrame:
    """
    Grundaufbereitung:
      - Pflichtspalten prüfen
      - Namen kanonisieren (+ optional Alias)
      - EventDate & Gewicht 'w' berechnen
      - Rollen-Flags setzen
      - Group (A/B) ableiten
    """
    required = {"EventID", "PlayerName", "RoleAtRegistration", "Teilgenommen"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(
            f"events benötigt Spalten {sorted(required)}, fehlen: {sorted(missing)}"
        )

    am = prepared_alias_map if prepared_alias_map is not None else prepare_alias_map(alias_map)

    df = events.copy()

    # Name → kanonisieren + alias
    df["PlayerName"] = df["PlayerName"].map(lambda x: _apply_alias_and_canon(x, am))

    # Teilnahme als 0/1 int
    df["Teilgenommen"] = pd.to_numeric(df["Teilgenommen"], errors="coerce").fillna(0).astype(int).clip(0, 1)

    # Event-Datum & Gewicht (rolling = exponentiell geglättet gegenüber reference_dt/now)
    now_dt = reference_dt or datetime.now(timezone.utc)
    df["EventDate"] = pd.to_datetime(
        df["EventID"].map(parse_event_date), utc=True, errors="coerce"
    )
    if reliability_start_date is not None:
        df = df[df["EventDate"].dt.date >= reliability_start_date].copy()
    df["w"] = df["EventDate"].map(
        lambda d: exp_decay_weight(d, now_dt=now_dt, half_life_days=half_life_days)
    )

    # Group (A/B) aus EventID – optional nützlich für spätere Auswertungen
    df["Group"] = df["EventID"].map(_extract_group)

    # Rollen-Masken
    df["role_start"] = df["RoleAtRegistration"].isin(ROLES_START)
    df["role_sub"] = df["RoleAtRegistration"].isin(ROLES_SUB)
    df["assigned"] = df["role_start"] | df["role_sub"]

    # Events ohne jeglichen Show-Eintrag (häufig Platzhalter/abgesagte Runs)
    # verzerren die Historie massiv, weil jede Zeile als No-Show gewertet würde.
    # Wir werfen daher EventIDs aus dem Datensatz, deren Start/Sub-Zeilen
    # ausschließlich Teilgenommen==0 enthalten.
    assigned_rows = df[df["assigned"]]
    if not assigned_rows.empty:
        event_attendance = assigned_rows.groupby("EventID")["Teilgenommen"].agg(
            ["sum", "size"]
        )
        missing_events = event_attendance[
            (event_attendance["sum"] <= 0) & (event_attendance["size"] >= 3)
        ].index
        if len(missing_events) > 0:
            df = df[~df["EventID"].isin(missing_events)].copy()

    return df


@dataclass(frozen=True)
class PlayerReliability:
    events: int
    attendance: int
    no_shows: int
    early_cancels: int
    late_cancels: int


def _agg_rates(df: pd.DataFrame, role_mask_col: str) -> pd.DataFrame:
    """
    Aggregiert (ungewichtet + gewichtet) pro Spieler für eine gegebene Rolle.
    Gibt Spalten:
      PlayerName, assignments, shows, noshow, show_rate, noshow_rate,
      last_event, w_assignments, w_shows, w_show_rate, w_noshow_rate
    """
    dfr = df[df[role_mask_col]].copy()
    if dfr.empty:
        # Leeres Grundgerüst (wichtig für saubere outer-joins)
        cols = [
            "PlayerName",
            "assignments",
            "shows",
            "noshow",
            "show_rate",
            "noshow_rate",
            "last_event",
            "w_assignments",
            "w_shows",
            "w_show_rate",
            "w_noshow_rate",
        ]
        return pd.DataFrame(columns=cols)

    grp = dfr.groupby("PlayerName", as_index=False)

    # Ungewichtet
    unweighted = grp.agg(
        assignments=("Teilgenommen", "size"),
        shows=("Teilgenommen", "sum"),
        last_event=("EventDate", "max"),
    )
    unweighted["noshow"] = (unweighted["assignments"] - unweighted["shows"]).astype(
        int
    )
    unweighted["show_rate"] = (
        unweighted["shows"] / unweighted["assignments"]
    ).where(unweighted["assignments"] > 0, 0.0)
    unweighted["noshow_rate"] = 1.0 - unweighted["show_rate"]

    # Gewichtet
    dfr["w_show"] = dfr["Teilgenommen"] * dfr["w"]
    wgrp = dfr.groupby("PlayerName", as_index=False).agg(
        w_assignments=("w", "sum"),
        w_shows=("w_show", "sum"),
    )
    wgrp["w_show_rate"] = (
        wgrp["w_shows"] / wgrp["w_assignments"]
    ).where(wgrp["w_assignments"] > 0, 0.0)
    wgrp["w_noshow_rate"] = 1.0 - wgrp["w_show_rate"]

    out = pd.merge(unweighted, wgrp, on="PlayerName", how="outer").fillna(0.0)
    out["last_event"] = pd.to_datetime(out["last_event"], utc=True, errors="coerce")
    return out


# ------------------------------------------------------------
# Öffentliche Funktionen
# ------------------------------------------------------------
def compute_role_probs(
    events: pd.DataFrame,
    *,
    alias_map: Optional[Dict[str, str]] = None,
    half_life_days: float = 90.0,
    reference_dt: Optional[datetime] = None,
    reliability_start_date: date | None = RELIABILITY_START_DATE,
) -> pd.DataFrame:
    """
    Liefert p_start/p_sub für den Roster-Builder auf Basis der Historie.
    p_* = gewichtete Show-Rate der jeweiligen Rolle (w_show_rate).

    Rückgabe-Columns:
      PlayerName, p_start, p_sub,
      start_assignments, start_shows, start_noshow, start_show_rate, start_noshow_rate,
      start_w_assignments, start_w_shows, start_w_show_rate, start_w_noshow_rate, start_last_event,
      sub_assignments,   sub_shows,   sub_noshow,   sub_show_rate,   sub_noshow_rate,
      sub_w_assignments, sub_w_shows, sub_w_show_rate, sub_w_noshow_rate, sub_last_event
    """
    df = _prep(
        events,
        alias_map=alias_map,
        half_life_days=half_life_days,
        reference_dt=reference_dt,
        reliability_start_date=reliability_start_date,
    )

    start_stats = _agg_rates(df, "role_start").add_prefix("start_")
    sub_stats = _agg_rates(df, "role_sub").add_prefix("sub_")

    all_players = pd.Index(start_stats["start_PlayerName"]).union(
        sub_stats["sub_PlayerName"]
    )
    out = pd.DataFrame({"PlayerName": all_players})

    out = out.merge(
        start_stats.rename(columns={"start_PlayerName": "PlayerName"}),
        on="PlayerName",
        how="left",
    )
    out = out.merge(
        sub_stats.rename(columns={"sub_PlayerName": "PlayerName"}),
        on="PlayerName",
        how="left",
    )

    # Wahrscheinlichkeiten (gewichtete Show-Rate)
    out["p_start"] = out["start_w_show_rate"].fillna(0.0).clip(0.0, 1.0)
    out["p_sub"] = out["sub_w_show_rate"].fillna(0.0).clip(0.0, 1.0)

    # Fehlende Analyse-Spalten robust ergänzen, Reihenfolge festziehen
    cols = [
        "PlayerName",
        "p_start",
        "p_sub",
        "start_assignments",
        "start_shows",
        "start_noshow",
        "start_show_rate",
        "start_noshow_rate",
        "start_w_assignments",
        "start_w_shows",
        "start_w_show_rate",
        "start_w_noshow_rate",
        "start_last_event",
        "sub_assignments",
        "sub_shows",
        "sub_noshow",
        "sub_show_rate",
        "sub_noshow_rate",
        "sub_w_assignments",
        "sub_w_shows",
        "sub_w_show_rate",
        "sub_w_noshow_rate",
        "sub_last_event",
    ]
    for c in cols:
        if c not in out.columns:
            out[c] = pd.NA
    out = out[cols]
    return out


def compute_player_history(
    events: pd.DataFrame,
    *,
    alias_map: Optional[Dict[str, str]] = None,
    half_life_days: float = 90.0,
    reference_dt: Optional[datetime] = None,
    reliability_start_date: date | None = RELIABILITY_START_DATE,
) -> pd.DataFrame:
    """
    Rollenübergreifende Metriken pro Spieler:
      assignments_total / shows_total / noshows_total
      show_rate / noshow_rate (ungewichtet)
      w_show_rate / w_noshow_rate (gewichtet)
      last_event
    """
    df = _prep(
        events,
        alias_map=alias_map,
        half_life_days=half_life_days,
        reference_dt=reference_dt,
        reliability_start_date=reliability_start_date,
    )
    dfa = df[df["assigned"]].copy()

    if dfa.empty:
        cols = [
            "PlayerName",
            "assignments_total",
            "shows_total",
            "noshows_total",
            "show_rate",
            "noshow_rate",
            "w_assignments_total",
            "w_shows_total",
            "w_show_rate",
            "w_noshow_rate",
            "last_event",
            "last_noshow_event",
        ]
        return pd.DataFrame(columns=cols)

    grp = dfa.groupby("PlayerName", as_index=False).agg(
        assignments_total=("Teilgenommen", "size"),
        shows_total=("Teilgenommen", "sum"),
    )
    grp["noshows_total"] = (
        grp["assignments_total"] - grp["shows_total"]
    ).astype(int)
    grp["show_rate"] = (
        grp["shows_total"] / grp["assignments_total"]
    ).where(grp["assignments_total"] > 0, 0.0)
    grp["noshow_rate"] = 1.0 - grp["show_rate"]

    dfa["w_show"] = dfa["Teilgenommen"] * dfa["w"]
    wgrp = dfa.groupby("PlayerName", as_index=False).agg(
        w_assignments_total=("w", "sum"),
        w_shows_total=("w_show", "sum"),
    )
    wgrp["w_show_rate"] = (
        wgrp["w_shows_total"] / wgrp["w_assignments_total"]
    ).where(wgrp["w_assignments_total"] > 0, 0.0)
    wgrp["w_noshow_rate"] = 1.0 - wgrp["w_show_rate"]

    show_events = dfa[dfa["Teilgenommen"] == 1][["PlayerName", "EventDate"]]
    if show_events.empty:
        last_show = pd.DataFrame({"PlayerName": [], "last_event": []})
    else:
        last_show = show_events.groupby("PlayerName", as_index=False).agg(
            last_event=("EventDate", "max")
        )

    noshow_events = dfa[dfa["Teilgenommen"] == 0][["PlayerName", "EventDate"]]
    if noshow_events.empty:
        last_noshow = pd.DataFrame({"PlayerName": [], "last_noshow_event": []})
    else:
        last_noshow = noshow_events.groupby("PlayerName", as_index=False).agg(
            last_noshow_event=("EventDate", "max")
        )

    out = pd.merge(grp, wgrp, on="PlayerName", how="outer")
    for col in [
        "assignments_total",
        "shows_total",
        "noshows_total",
        "show_rate",
        "noshow_rate",
        "w_assignments_total",
        "w_shows_total",
        "w_show_rate",
        "w_noshow_rate",
    ]:
        if col in out.columns:
            out[col] = out[col].fillna(0.0)

    out = out.merge(last_show, on="PlayerName", how="left")
    out = out.merge(last_noshow, on="PlayerName", how="left")
    out["last_event"] = pd.to_datetime(out["last_event"], utc=True, errors="coerce")
    out["last_noshow_event"] = pd.to_datetime(
        out["last_noshow_event"], utc=True, errors="coerce"
    )
    return out.sort_values(
        ["noshow_rate", "w_noshow_rate", "PlayerName"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def _extract_effective_state(row: Mapping[str, object]) -> EffectiveSignupState | None:
    for key in ["effective_signup_state", "EffectiveSignupState", "effective_state"]:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return EffectiveSignupState(str(value))
        except ValueError:
            return None
    return None


def compute_player_reliability(
    events: pd.DataFrame,
    *,
    alias_map: Optional[Dict[str, str]] = None,
    half_life_days: float = 90.0,
    reference_dt: Optional[datetime] = None,
    reliability_start_date: date | None = RELIABILITY_START_DATE,
) -> Dict[str, PlayerReliability]:
    """
    Berechnet Zuverlässigkeits-Kennzahlen pro Spieler (ab reliability_start_date).

    Events werden über ``_prep`` vorverarbeitet (Alias/Canon, Rollen-Filter).
    Ereignisse mit dem EffectiveSignupState ``none`` werden ignoriert, alle
    anderen fließen in den events-Zähler ein.
    """

    prepared_alias_map = prepare_alias_map(alias_map)
    df = _prep(
        events,
        alias_map=None,
        prepared_alias_map=prepared_alias_map,
        half_life_days=half_life_days,
        reference_dt=reference_dt,
        reliability_start_date=reliability_start_date,
    )

    dfa = df[df["assigned"]].copy()
    if dfa.empty:
        return {}

    relevant_event_ids = set(dfa["EventID"].unique())
    seen_raw_names = set()
    if not events.empty and "PlayerName" in events.columns:
        seen_raw_names = {
            str(name)
            for name in events[events["EventID"].isin(relevant_event_ids)]["PlayerName"].dropna()
        }

    stats: Dict[str, PlayerReliability] = {}

    for row in dfa.itertuples(index=False):
        player = getattr(row, "PlayerName")
        state = _extract_effective_state(row._asdict())
        # Determine effective signup state; default to HARD_ACTIVE when assigned
        if state is None:
            state = EffectiveSignupState.HARD_ACTIVE
        if state == EffectiveSignupState.NONE:
            continue

        current = stats.get(
            player,
            PlayerReliability(
                events=0, attendance=0, no_shows=0, early_cancels=0, late_cancels=0
            ),
        )

        events_count = current.events + 1
        attendance = current.attendance
        no_shows = current.no_shows
        early_cancels = current.early_cancels
        late_cancels = current.late_cancels

        if state == EffectiveSignupState.CANCELLED_EARLY:
            early_cancels += 1
        elif state == EffectiveSignupState.CANCELLED_LATE:
            late_cancels += 1
        else:
            attended = int(getattr(row, "Teilgenommen", 0))
            attendance += attended
            if attended == 0:
                no_shows += 1

        stats[player] = PlayerReliability(
            events=events_count,
            attendance=attendance,
            no_shows=no_shows,
            early_cancels=early_cancels,
            late_cancels=late_cancels,
        )

    normalized_from_raw = {
        raw: _apply_alias_and_canon(raw, prepared_alias_map) for raw in seen_raw_names
    }
    seen_normalized_names = set(stats.keys())

    ignored_raw = sorted({raw for raw, norm in normalized_from_raw.items() if not norm})
    if ignored_raw:
        print(
            "[reliability] Ignored raw player names (after normalization empty/invalid): "
            + ", ".join(ignored_raw)
        )

    missing_normalized = sorted(
        {norm for norm in normalized_from_raw.values() if norm and norm not in seen_normalized_names}
    )
    if missing_normalized:
        print(
            "[reliability] Normalized player names missing from stats (filtered/role mismatch?): "
            + ", ".join(missing_normalized)
        )

    return stats


def _quantile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    q = min(max(q, 0.0), 1.0)
    pos = q * (len(sorted_vals) - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return sorted_vals[low]
    frac = pos - low
    return sorted_vals[low] + (sorted_vals[high] - sorted_vals[low]) * frac


def compute_team_prior(rates: List[float], winsor: bool, fallback: float) -> float:
    clean: List[float] = []
    for r in rates:
        try:
            val = float(r)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(val):
            continue
        if val < 0.0 or val > 1.0:
            continue
        clean.append(val)

    if not clean:
        return float(fallback)

    clean.sort()
    if winsor and len(clean) >= 10:
        lower = _quantile(clean, 0.05)
        upper = _quantile(clean, 0.95)
        clean = [min(max(v, lower), upper) for v in clean]
        mean = sum(clean) / len(clean)
    elif winsor:
        mean = float(fallback)
    else:
        mean = sum(clean) / len(clean)

    mean = min(max(mean, 0.0), 1.0)
    if not math.isfinite(mean):
        return float(fallback)
    return mean


def eb_rate(s: int, n: int, p0: float, n0: float) -> tuple[float, float]:
    p0 = float(p0)
    p0 = min(max(p0, 0.0), 1.0)
    try:
        n = float(n)
    except (TypeError, ValueError):
        n = 0.0
    try:
        s = float(s)
    except (TypeError, ValueError):
        s = 0.0

    n = max(n, 0.0)
    s = min(max(s, 0.0), n)
    n0 = max(float(n0), 0.0)

    alpha0 = p0 * n0
    beta0 = (1.0 - p0) * n0

    alpha = alpha0 + s
    beta = beta0 + (n - s)
    total = alpha + beta

    if total <= 0:
        return p0, 0.0

    p_hat = alpha / total
    var = (alpha * beta) / (total * total * (total + 1.0)) if total > 1.0 else 0.0
    var = max(var, 0.0)
    sigma = math.sqrt(var)
    return p_hat, sigma


def eb_score(p_hat: float, sigma: float, lam: float) -> float:
    return float(p_hat) + float(lam) * float(sigma)


__all__ = [
    "compute_role_probs",
    "compute_player_history",
    "compute_player_reliability",
    "PlayerReliability",
    "prepare_alias_map",
    "compute_team_prior",
    "eb_rate",
    "eb_score",
    "RELIABILITY_START_DATE",
    "RELIABILITY_START_DATE_RAW",
]
