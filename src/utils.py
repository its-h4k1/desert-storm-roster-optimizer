# -*- coding: utf-8 -*-
"""
utils.py – Helfer für Roster-Building, Namensnormalisierung und Event-Gewichtung.
Kompatibel mit main.py (deterministic-only) und stats.py (parse_event_date/exp_decay_weight).

Korrekturen:
- canonical_name: jetzt mit Lowercasing (fix für „Evil Activities“ vs „Evil activities“).
- Robuste Defaults für Pref*-Spalten (kein .fillna() mehr auf Skalar).
- _ensure_prob: liefert immer eine Series (Skalar-Fallback entfernt).
"""

from __future__ import annotations
import re
from datetime import datetime, timezone
import unicodedata
import pandas as pd
from typing import List, Dict, Set

from src.config import get_config

# ----------------------------
# Globale Roster-Kapazitäten
# ----------------------------
STARTERS_PER_GROUP = 20
SUBS_PER_GROUP = 10
GROUPS = ["A", "B"]

# --------------------------------------------
# Namensnormalisierung (Zero-Width + Homoglyph)
# --------------------------------------------
_ZW_REMOVALS = {
    "\u200b": "",  # ZERO WIDTH SPACE
    "\u200c": "",  # ZERO WIDTH NON-JOINER
    "\u200d": "",  # ZERO WIDTH JOINER
    "\u200e": "",  # LEFT-TO-RIGHT MARK
    "\u200f": "",  # RIGHT-TO-LEFT MARK
    "\u2060": "",  # WORD JOINER
    "\ufeff": "",  # ZERO WIDTH NO-BREAK SPACE (BOM)
}

# Häufige Cyrillic→Latin Lookalikes, die in Spielnamen auftauchen können
HOMO_TRANSLATE = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "S", "Т": "T", "Х": "X", "І": "I", "Ј": "J", "У": "Y",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "s", "х": "x", "у": "y",
    "к": "k", "м": "m", "т": "t", "н": "h", "і": "i", "ј": "j", "ѵ": "y",
})

def canonical_name(s: str) -> str:
    """
    Normalisiert Spieler-Namen deterministisch:
    - Unicode NFKC
    - Zero-Width-/Formatierungszeichen entfernen
    - Cyrillic-Homoglyphen nach Latin falten
    - lowercasing
    - Whitespace kollabieren + trimmen
    """
    s = unicodedata.normalize("NFKC", str(s))
    for k, v in _ZW_REMOVALS.items():
        s = s.replace(k, v)
    s = s.translate(HOMO_TRANSLATE)
    s = s.lower()
    s = " ".join(s.split())
    return s.strip()

# --------------------------------------
# Deterministischer Roster-Builder
# --------------------------------------
_CFG = get_config()


def build_deterministic_roster(
    probs_df: pd.DataFrame,
    *,
    forced_assignments: List[Dict[str, str]] | None = None,
    capacities_by_group_role: Dict[str, Dict[str, int]] | None = None,
) -> pd.DataFrame:
    """
    Baut eine eindeutige Aufstellung ohne Doppler unter Berücksichtigung von
    Gruppenpräferenzen (hard/soft) und Boosts.

    Erwartete Spalten (mindestens):
      - PlayerName
      - p_start[_A|_B] (optional gruppenspezifisch, sonst p_start global)
      - p_sub[_A|_B]   (optional gruppenspezifisch, sonst p_sub global)
      - PrefGroup (A|B) optional
      - PrefMode  (hard|soft) optional
      - PrefBoost (0..1) optional, Standard 0.05 wenn PrefGroup passt und Boost<=0

    Erweiterungen für harte Zusagen:
      - forced_assignments: Liste vorberechneter Slots (PlayerName, Group, Role)
        die vor dem Optimizer gesetzt werden.
      - capacities_by_group_role: Rest-Kapazitäten pro Gruppe/Rolle für den
        Optimizer (z. B. 15 Starter, wenn 5 Slots bereits hart belegt sind).
    """
    forced_assignments = forced_assignments or []
    df = probs_df.copy()
    if "PlayerName" not in df.columns:
        raise ValueError("probs_df benötigt eine Spalte 'PlayerName'")

    # Namen vereinheitlichen und je Spieler nur 1 Zeile behalten
    df["PlayerName"] = df["PlayerName"].map(canonical_name)
    df = df.drop_duplicates(subset=["PlayerName"], keep="first").reset_index(drop=True)

    has_events_seen = "events_seen" in df.columns
    if has_events_seen:
        df["events_seen"] = (
            pd.to_numeric(df["events_seen"], errors="coerce")
            .fillna(0)
            .astype(int)
        )

    if "risk_penalty" in df.columns:
        df["risk_penalty"] = (
            pd.to_numeric(df["risk_penalty"], errors="coerce")
            .fillna(0.0)
            .clip(lower=0.0)
        )
    else:
        df["risk_penalty"] = pd.Series([0.0] * len(df), index=df.index)

    # Präferenz-Spalten robust befüllen (immer Series mit Index df.index)
    df["PrefGroup"] = (
        df["PrefGroup"].astype(str).str.upper()
        if "PrefGroup" in df.columns
        else pd.Series([""] * len(df), index=df.index)
    )
    df["PrefMode"] = (
        df["PrefMode"].astype(str).str.lower()
        if "PrefMode" in df.columns
        else pd.Series([""] * len(df), index=df.index)
    )
    if "PrefBoost" in df.columns:
        df["PrefBoost"] = pd.to_numeric(df["PrefBoost"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
    else:
        df["PrefBoost"] = pd.Series([0.0] * len(df), index=df.index)

    # Gruppenbezogene Wahrscheinlichkeiten sicherstellen → immer Series
    def _ensure_prob(col_base: str, group: str) -> pd.Series:
        col_name = f"{col_base}_{group}"
        if col_name in df.columns:
            series = pd.to_numeric(df[col_name], errors="coerce").fillna(0.0)
        elif col_base in df.columns:
            series = pd.to_numeric(df[col_base], errors="coerce").fillna(0.0)
        else:
            series = pd.Series([0.0] * len(df), index=df.index)
        return series

    for g in GROUPS:
        df[f"p_start_{g}"] = _ensure_prob("p_start", g).clip(0.0, 1.0)
        df[f"p_sub_{g}"]   = _ensure_prob("p_sub", g).clip(0.0, 1.0)

    # Boosts nur in gewünschter Gruppe addieren (Standard 0.05 bei leerem Boost)
    for g in GROUPS:
        mask = df["PrefGroup"] == g
        # Standard-Boost 0.05, wenn Gruppe passt und Boost nicht gesetzt/<=0
        eff_boost = df["PrefBoost"].where(mask, 0.0)
        eff_boost = eff_boost.mask(mask & (eff_boost <= 0.0), 0.05)

        base_start = df[f"p_start_{g}"] + eff_boost
        base_sub = df[f"p_sub_{g}"] + eff_boost
        df[f"score_{g}_start"] = (base_start - df["risk_penalty"]).clip(0.0, 1.0)
        df[f"score_{g}_sub"]   = (base_sub   - df["risk_penalty"]).clip(0.0, 1.0)

    used: Set[str] = set()
    rows: List[Dict[str, str]] = []

    # Vorbelegte Slots (harte Zusagen)
    caps = {
        g: {"Start": STARTERS_PER_GROUP, "Ersatz": SUBS_PER_GROUP}
        for g in GROUPS
    }
    if capacities_by_group_role:
        for g in GROUPS:
            for r in ["Start", "Ersatz"]:
                try:
                    val = int(capacities_by_group_role.get(g, {}).get(r, caps[g][r]))
                except Exception:
                    val = caps[g][r]
                caps[g][r] = max(0, val)

    forced_count = {g: {"Start": 0, "Ersatz": 0} for g in GROUPS}
    for item in forced_assignments:
        g = str(item.get("Group", "")).strip().upper()
        r = str(item.get("Role", "")).strip().title()
        p = canonical_name(item.get("PlayerName", ""))
        if not p or g not in GROUPS or r not in {"Start", "Ersatz"}:
            continue
        if p in used:
            continue
        used.add(p)
        rows.append({"PlayerName": p, "Group": g, "Role": r})
        forced_count[g][r] += 1

    start_no_data_cap = getattr(_CFG, "START_NO_DATA_CAP", 0)
    start_no_data_taken = {g: 0 for g in GROUPS}
    guard_enabled = has_events_seen and start_no_data_cap >= 0

    def _sort_candidates(group: str, role: str) -> pd.DataFrame:
        score_col = f"score_{group}_{'start' if role == 'Start' else 'sub'}"
        primary = f"p_{'start' if role == 'Start' else 'sub'}_{group}"
        secondary = f"p_{'sub' if role == 'Start' else 'start'}_{group}"
        return (
            df[~df["PlayerName"].isin(used)]
            .copy()
            .sort_values(
                [score_col, primary, secondary, "PlayerName"],
                ascending=[False, False, False, True],
                kind="mergesort",  # stabil
            )
        )

    def _pick_for(group: str, role: str, count: int) -> pd.DataFrame:
        candidates = _sort_candidates(group, role)
        if candidates.empty:
            return candidates

        pref_group = candidates["PrefGroup"].astype(str).str.upper()
        pref_mode  = candidates["PrefMode"].astype(str).str.lower()

        recognized_pref = pref_group.isin(GROUPS)
        cat1 = (pref_group == group) & (pref_mode == "hard")  # Muss nehmen, wenn vorhanden
        cat2 = (pref_group == group) & (pref_mode == "soft")  # Bevorzugt
        cat3 = (
            ~(cat1 | cat2) &
            ((pref_group == group) | (~recognized_pref) | (pref_group == ""))
        )  # neutral/gleich/fallback
        cat4 = (
            ~(cat1 | cat2 | cat3) &
            (pref_group.isin(GROUPS)) & (pref_group != group) & (pref_mode != "hard")
        )  # andere Gruppe, aber nicht hard
        cat5 = (
            (pref_group.isin(GROUPS)) & (pref_group != group) & (pref_mode == "hard")
        )  # andere Gruppe hard → nur wenn Slots sonst leer blieben

        categories = [cat1, cat2, cat3, cat4, cat5]
        selected_frames: List[pd.DataFrame] = []
        selected_names: Set[str] = set()
        remaining = count

        def _take_from(available_df: pd.DataFrame, remaining_slots: int) -> tuple[pd.DataFrame, int]:
            if remaining_slots <= 0 or available_df.empty:
                return pd.DataFrame(columns=available_df.columns), remaining_slots

            chosen_idx: List[int] = []
            local_remaining = remaining_slots
            for idx, row in available_df.iterrows():
                if local_remaining <= 0:
                    break
                is_no_data = False
                if guard_enabled and role == "Start":
                    ev_val = row.get("events_seen")
                    try:
                        ev_int = int(ev_val)
                    except (TypeError, ValueError):
                        ev_int = 0
                    is_no_data = ev_int <= 0
                    if is_no_data and start_no_data_taken[group] >= start_no_data_cap:
                        continue
                chosen_idx.append(idx)
                local_remaining -= 1
                if guard_enabled and role == "Start" and is_no_data:
                    start_no_data_taken[group] += 1

            if not chosen_idx:
                return pd.DataFrame(columns=available_df.columns), remaining_slots
            return available_df.loc[chosen_idx], local_remaining

        for mask in categories:
            if remaining <= 0:
                break
            available = candidates[mask & (~candidates["PlayerName"].isin(selected_names))]
            if available.empty:
                continue
            take, remaining = _take_from(available, remaining)
            if take.empty:
                continue
            selected_frames.append(take)
            selected_names.update(take["PlayerName"].tolist())

        if remaining > 0:
            fallback = candidates[~candidates["PlayerName"].isin(selected_names)]
            if not fallback.empty:
                take, remaining = _take_from(fallback, remaining)
                if not take.empty:
                    selected_frames.append(take)
                    selected_names.update(take["PlayerName"].tolist())

        if remaining > 0:
            # An dieser Stelle fehlen uns real Kandidaten (z. B. vorher gefiltert/inaktiv)
            raise RuntimeError(f"Not enough candidates to fill {group} {role} (missing {remaining}).")

        return (
            pd.concat(selected_frames, ignore_index=True)
            if selected_frames else
            pd.DataFrame(columns=candidates.columns)
        )

    # Slots in definierter Reihenfolge füllen
    order = [
        ("A", "Start",  caps["A"]["Start"]),
        ("B", "Start",  caps["B"]["Start"]),
        ("A", "Ersatz", caps["A"]["Ersatz"]),
        ("B", "Ersatz", caps["B"]["Ersatz"]),
    ]

    for group, role, cap in order:
        picked = _pick_for(group, role, cap)
        for row in picked.itertuples(index=False):
            used.add(row.PlayerName)
            rows.append({"PlayerName": row.PlayerName, "Group": group, "Role": role})

    out = pd.DataFrame(rows, columns=["PlayerName", "Group", "Role"])

    # Safety: harte Assertions (kein Doppler, exakt Zielanzahl inkl. forced Slots)
    assert not out.duplicated("PlayerName").any(), "Duplicate players in roster"
    for g in GROUPS:
        target_start = caps[g]["Start"] + forced_count[g]["Start"]
        target_sub = caps[g]["Ersatz"] + forced_count[g]["Ersatz"]
        assert len(out[(out["Group"] == g) & (out["Role"] == "Start")])  == target_start, f"Wrong starters in {g}"
        assert len(out[(out["Group"] == g) & (out["Role"] == "Ersatz")]) == target_sub,   f"Wrong subs in {g}"

    return out

# ------------------------------------------------
# Für stats.py: EventID-Datum & Zeitgewichtung
# ------------------------------------------------
_EVENT_ID_RE = re.compile(r"^DS-(\d{4})-(\d{2})-(\d{2})-[A-Z]$", re.IGNORECASE)

def parse_event_date(event_id: str) -> datetime:
    """
    Erwartet EventID wie DS-YYYY-MM-DD-A und liefert ein UTC-Datum.
    Fallback: now() bei unbekanntem Format.
    """
    s = str(event_id).strip()
    m = _EVENT_ID_RE.match(s)
    if not m:
        return datetime.now(timezone.utc)
    y, mo, d = map(int, m.groups())
    return datetime(y, mo, d, tzinfo=timezone.utc)

def exp_decay_weight(event_dt: datetime, now_dt: datetime | None = None, half_life_days: float = 90.0) -> float:
    """
    Exponentielle Abwertung älterer Events:
      weight = 0.5 ** (delta_days / half_life_days)
    """
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    delta_days = max(0.0, (now_dt - event_dt).total_seconds() / 86400.0)
    try:
        hl = float(half_life_days)
    except Exception:
        hl = 90.0
    if hl <= 0:
        return 1.0
    return 0.5 ** (delta_days / hl)

# Öffentliche Symbole
def load_alias_map(path: str, *, max_depth: int | None = None) -> Dict[str, str]:
    """Lazy re-export to keep the historical public API stable."""

    from .alias_utils import load_alias_map as _load_alias_map

    if max_depth is None:
        return _load_alias_map(path)
    return _load_alias_map(path, max_depth=max_depth)


__all__ = [
    "canonical_name",
    "build_deterministic_roster",
    "parse_event_date",
    "exp_decay_weight",
    "STARTERS_PER_GROUP",
    "SUBS_PER_GROUP",
    "GROUPS",
    "load_alias_map",
]
