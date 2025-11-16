# -*- coding: utf-8 -*-
"""
debug_missing_metrics.py — Diagnosereport für fehlende No-Show-Metriken

Zweck
- Prüft die aktuelle Aufstellung (out/latest.json) gegen die Event-Historie (data/*.csv)
- Meldet Spieler in der aktuellen Aufstellung, für die KEINE No-Show-Metriken vorliegen:
  * Reason = "no_history"    → keine Events gefunden
  * Reason = "missing_metric"→ Events vorhanden, aber Metriken fehlen (i. d. R. Join/Canon/Alias-Problem)

Eingaben (typisch im CI-Step):
  python -u -m src.debug_missing_metrics \
    --events "data/*.csv" \
    --alliance "data/alliance.csv" \
    --aliases "data/aliases.csv" \
    --latest "out/latest.json" \
    --out "out/missing_noshow_report.csv"

Ausgabe
- CSV mit Spalten:
  PlayerName,Group,Role,NoShowOverall,NoShowRolling,Reason,SeenEvents,LastSeenDate,Canonical,AliasedFrom,InAlliance,ActiveFlag
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.alias_utils import AliasResolutionError, load_alias_map
from src.utils import canonical_name, parse_event_date


EVENT_RE = re.compile(r"^DS-\d{4}-\d{2}-\d{2}-[A-Z]$", re.IGNORECASE)


# --------------------------
# Loader & Utils
# --------------------------
def _normalize_event_patterns(ev_args: List[str]) -> List[str]:
    pats: List[str] = []
    for item in ev_args:
        if not item:
            continue
        pats.extend([p for p in re.split(r"\s+", item.strip()) if p])
    return pats


def _glob_paths(patterns: List[str]) -> List[Path]:
    out: List[Path] = []
    for pat in patterns:
        for p in Path(".").glob(pat):
            if p.is_file():
                out.append(p)
    # stabil deduplizieren
    seen = set()
    uniq: List[Path] = []
    for p in out:
        rp = p.resolve()
        if rp not in seen:
            uniq.append(p)
            seen.add(rp)
    return uniq


def _load_events(event_patterns: List[str]) -> pd.DataFrame:
    paths = _glob_paths(event_patterns)
    keep: List[pd.DataFrame] = []
    for p in paths:
        name = p.name.lower()
        if name.endswith(("alliance.csv", "aliases.csv", "absences.csv", "preferences.csv")):
            continue
        try:
            df = pd.read_csv(p)
        except Exception as e:
            print(f"[warn] CSV nicht lesbar ({p}): {e}")
            continue
        need = {"EventID", "Slot", "PlayerName", "RoleAtRegistration"}
        if not need.issubset(df.columns):
            continue
        sample = df["EventID"].dropna().astype(str)
        if sample.empty or not sample.map(lambda s: bool(EVENT_RE.match(s))).all():
            continue
        if "Teilgenommen" not in df.columns:
            df["Teilgenommen"] = 0
        df["Teilgenommen"] = pd.to_numeric(df["Teilgenommen"], errors="coerce").fillna(0).astype(int).clip(0, 1)
        keep.append(df[["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"]].copy())

    if not keep:
        return pd.DataFrame(columns=["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"])
    return pd.concat(keep, ignore_index=True)


def _ensure_in_alliance_column(df: pd.DataFrame, *, context: str) -> pd.Series:
    """Normalize the InAlliance membership flag with Active as a legacy alias."""

    if "InAlliance" in df.columns:
        column = "InAlliance"
    elif "Active" in df.columns:
        print(
            f"[warn] {context}: legacy column 'Active' gefunden – bitte künftig 'InAlliance' verwenden."
        )
        column = "Active"
    else:
        raise SystemExit(
            f"[fatal] {context} benötigt die Spalte 'InAlliance' (oder legacy 'Active')."
        )

    df["InAlliance"] = (
        pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int).clip(0, 1)
    )
    return df["InAlliance"]


def _load_alliance(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    if "PlayerName" not in df.columns:
        raise SystemExit("[fatal] alliance.csv benötigt Spalte 'PlayerName'")

    _ensure_in_alliance_column(df, context="alliance.csv")
    df["DisplayName"] = df["PlayerName"].astype(str)
    df["canon"] = df["PlayerName"].map(canonical_name)
    return df[["canon", "DisplayName", "InAlliance"]].copy()


def _load_latest_json(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"[fatal] latest.json nicht gefunden: {path}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"[fatal] latest.json defekt: {e}")


def _apply_alias_and_canon(name: str, alias_map: Dict[str, str]) -> Tuple[str, Optional[str]]:
    """
    Gibt (canon, aliased_from) zurück. aliased_from ist gefüllt, wenn ein Mapping angewendet wurde.
    """
    raw = canonical_name(name)
    mapped = alias_map.get(raw, raw)
    return mapped, (raw if mapped != raw else None)


# --------------------------
# Diagnose-Logik
# --------------------------
def _compute_seen(events: pd.DataFrame, alias_map: Dict[str, str]) -> pd.DataFrame:
    """
    Liefert pro kanonischem Namen:
      canon, SeenEvents, LastSeenDate (YYYY-MM-DD)
    """
    if events.empty:
        return pd.DataFrame(columns=["canon", "SeenEvents", "LastSeenDate"])

    # Canon + Alias anwenden
    def _canon(name: str) -> str:
        c = canonical_name(name)
        return alias_map.get(c, c)

    df = events.copy()
    df["canon"] = df["PlayerName"].map(_canon)
    # Event-Datum aus EventID
    df["EventDate"] = pd.to_datetime(df["EventID"].map(parse_event_date), utc=True, errors="coerce")

    grp = df.groupby("canon", as_index=False).agg(
        SeenEvents=("EventID", "nunique"),
        LastSeen=("EventDate", "max"),
    )
    grp["LastSeenDate"] = grp["LastSeen"].dt.strftime("%Y-%m-%d")
    return grp[["canon", "SeenEvents", "LastSeenDate"]]


def build_missing_report(
    latest: dict,
    alliance_df: pd.DataFrame,
    events_seen_df: pd.DataFrame,
    alias_map: Dict[str, str],
) -> pd.DataFrame:
    """
    Baut den Missing-Report nur für Spieler, die in der aktuellen Aufstellung (latest.json) stehen.
    """
    players = latest.get("players", [])
    rows = []
    active_map = dict(zip(alliance_df["canon"], alliance_df["InAlliance"]))
    display_map = dict(zip(alliance_df["canon"], alliance_df["DisplayName"]))

    seen_map = dict(zip(events_seen_df["canon"], events_seen_df["SeenEvents"]))
    last_map = dict(zip(events_seen_df["canon"], events_seen_df["LastSeenDate"]))

    for p in players:
        display = p.get("display") or p.get("PlayerName") or ""
        group   = p.get("group") or p.get("Group") or ""
        role    = p.get("role")  or p.get("Role")  or ""
        ns_overall = p.get("noshow_overall", None)
        ns_rolling = p.get("noshow_rolling", None)
        canon_from_json = p.get("canon", "")

        # Canon bestimmen + AliasedFrom aus Sicht der Display-Quelle
        if canon_from_json:
            canon = canonical_name(canon_from_json)
            aliased_from = None
        else:
            canon, aliased_from = _apply_alias_and_canon(display, alias_map)

        # Zahlen ordentlich in NaN überführen falls None
        ns_overall = float(ns_overall) if isinstance(ns_overall, (float, int)) and not math.isnan(ns_overall) else float("nan")
        ns_rolling = float(ns_rolling) if isinstance(ns_rolling, (float, int)) and not math.isnan(ns_rolling) else float("nan")

        seen = int(seen_map.get(canon, 0) or 0)
        last = last_map.get(canon, "")

        # Alliance-Status
        active_flag = int(active_map.get(canon, 0))
        in_alliance = 1 if active_flag == 1 else 0

        # Reason
        if (math.isnan(ns_overall) and math.isnan(ns_rolling)):
            reason = "missing_metric" if seen > 0 else "no_history"
        else:
            # Metriken vorhanden → nicht im Report
            continue

        rows.append({
            "PlayerName": display_map.get(canon, display) or display,
            "Group": group,
            "Role": role,
            "NoShowOverall": "" if math.isnan(ns_overall) else ns_overall,
            "NoShowRolling": "" if math.isnan(ns_rolling) else ns_rolling,
            "Reason": reason,
            "SeenEvents": seen,
            "LastSeenDate": last,
            "Canonical": canon,
            "AliasedFrom": aliased_from if aliased_from else "",
            "InAlliance": in_alliance,
            "ActiveFlag": active_flag,
        })

    cols = [
        "PlayerName","Group","Role","NoShowOverall","NoShowRolling",
        "Reason","SeenEvents","LastSeenDate","Canonical","AliasedFrom",
        "InAlliance","ActiveFlag"
    ]
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values(["Reason","Group","Role","PlayerName"]).reset_index(drop=True)


# --------------------------
# CLI
# --------------------------
def main():
    ap = argparse.ArgumentParser(description="Diagnose fehlender No-Show-Metriken für aktuelle Aufstellung")
    ap.add_argument("--events", nargs="+", required=True, help="Glob-Pattern(s) für Event-CSV(s)")
    ap.add_argument("--alliance", required=True, help="Pfad zu data/alliance.csv")
    ap.add_argument("--aliases", default="", help="Pfad zu data/aliases.csv (optional)")
    ap.add_argument("--latest", default="out/latest.json", help="Pfad zu out/latest.json")
    ap.add_argument("--out", required=True, help="Pfad zur Ergebnis-CSV (z. B. out/missing_noshow_report.csv)")
    args = ap.parse_args()

    # Laden
    patterns = _normalize_event_patterns(args.events)
    events_df = _load_events(patterns)
    alliance_df = _load_alliance(args.alliance)
    alias_map = {}
    if args.aliases:
        try:
            alias_map = load_alias_map(args.aliases)
        except AliasResolutionError as e:
            print(f"[warn] aliases konnten nicht geladen werden: {e}")
        except Exception as e:
            print(f"[warn] aliases konnten nicht geladen werden: {e}")

    latest = _load_latest_json(args.latest)

    # Seen/Last berechnen
    events_seen_df = _compute_seen(events_df, alias_map)

    # Report bauen
    report = build_missing_report(latest, alliance_df, events_seen_df, alias_map)

    # Schreiben
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(out_path, index=False)
    print(f"[ok] wrote {out_path} ({len(report)} rows)")

    # Kleiner Head-Preview für Logs
    if not report.empty:
        print("--- missing_noshow_report.csv (head) ---")
        print(report.head(10).to_csv(index=False).strip())


if __name__ == "__main__":
    main()
