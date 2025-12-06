# -*- coding: utf-8 -*-
"""
main.py — Bau der deterministischen Desert-Storm-Aufstellung
Siehe README im Repo für Details.

Fixes:
- Fallback-Loader für aliases.csv, falls src.utils.load_alias_map nicht existiert.
- Robustere Verarbeitung von --events (multiline/globs).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

import pandas as pd

from src.config import get_config
from src.attendance_config import load_attendance_config
from src.callup_config import load_callup_config
from src.utils import (
    canonical_name,
    build_deterministic_roster,
    STARTERS_PER_GROUP,
    SUBS_PER_GROUP,
    GROUPS,
    MIN_B_STARTERS,
    parse_event_date,
)
from src.alias_utils import load_alias_map, AliasResolutionError

from src.stats import (
    compute_role_probs,
    compute_player_history,
    compute_team_prior,
    eb_rate,
)

EVENT_RE = re.compile(r"^DS-\d{4}-\d{2}-\d{2}-[A-Z]$", re.IGNORECASE)
TZ = ZoneInfo("Europe/Zurich")


# --------------------------
# Helpers: I/O + Normalizer
# --------------------------
def _normalize_event_patterns(ev_args: List[str]) -> List[str]:
    """
    Nimmt evtl. multiline/verkettete --events-Argumente und splittet auf Whitespace.
    Beispiel:
      ['data/*.csv'] -> ['data/*.csv']
      ['data/A.csv\ndata/B.csv'] -> ['data/A.csv','data/B.csv']
    """
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
    # Deduplizieren, stabil
    seen = set()
    uniq: List[Path] = []
    for p in out:
        rp = p.resolve()
        if rp not in seen:
            uniq.append(p)
            seen.add(rp)
    return uniq


def _read_csv_safe(path: Path) -> Optional[pd.DataFrame]:
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"[warn] CSV nicht lesbar ({path}): {e}")
        return None


def _is_event_df(df: pd.DataFrame) -> bool:
    need = {"EventID", "Slot", "PlayerName", "RoleAtRegistration"}
    if not need.issubset(df.columns):
        return False
    sample = df["EventID"].dropna().astype(str)
    if sample.empty:
        return False
    return sample.map(lambda s: bool(EVENT_RE.match(s))).all()


def _ensure_in_alliance_column(df: pd.DataFrame, *, context: str) -> pd.Series:
    """Normalize the ``InAlliance`` membership flag with a legacy fallback.

    ``InAlliance`` encodes whether a player currently belongs to the Desert-Storm
    alliance (1 = Mitglied, 0 = ausgetreten). Older CSVs may still ship the
    column as ``Active``; we interpret it identically but ask the caller to
    migrate.
    """

    if "InAlliance" in df.columns:
        source_col = "InAlliance"
    elif "Active" in df.columns:
        print(
            f"[warn] {context}: legacy column 'Active' gefunden – bitte in 'InAlliance' umbenennen."
        )
        source_col = "Active"
    else:
        raise SystemExit(
            f"[fatal] {context} benötigt die Spalte 'InAlliance' (oder legacy 'Active')."
        )

    df["InAlliance"] = (
        pd.to_numeric(df[source_col], errors="coerce")
        .fillna(0)
        .astype(int)
        .clip(0, 1)
    )
    return df["InAlliance"]


def _load_events(event_patterns: List[str]) -> pd.DataFrame:
    paths = _glob_paths(event_patterns)
    keep: List[pd.DataFrame] = []
    for p in paths:
        name = p.name.lower()
        if name.endswith(("alliance.csv", "aliases.csv", "absences.csv", "preferences.csv")):
            continue
        df = _read_csv_safe(p)
        if df is None:
            continue
        if _is_event_df(df):
            if "Teilgenommen" not in df.columns:
                df["Teilgenommen"] = 0
            df["Teilgenommen"] = pd.to_numeric(df["Teilgenommen"], errors="coerce").fillna(0).astype(int).clip(0, 1)
            keep.append(df[["EventID", "Slot", "PlayerName", "RoleAtRegistration", "Teilgenommen"]].copy())
    if not keep:
        raise SystemExit("[fatal] Keine gültigen Event-CSVs gefunden.")
    return pd.concat(keep, ignore_index=True)


def _load_alliance(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    if "PlayerName" not in df.columns:
        raise SystemExit("[fatal] alliance.csv benötigt Spalte 'PlayerName']")

    _ensure_in_alliance_column(df, context="alliance.csv")
    # InAlliance = 1 → Spieler gehört aktuell zur Allianz; 0 → ausgetreten/ignoriert.
    df["DisplayName"] = df["PlayerName"].astype(str)
    df["canon"] = df["PlayerName"].map(canonical_name)
    for col in ["PrefGroup", "PrefMode", "PrefBoost"]:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def _load_preferences(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    need = {"PlayerName", "PrefGroup"}
    if not need.issubset(df.columns):
        raise SystemExit("[fatal] preferences.csv benötigt mindestens PlayerName,PrefGroup")
    df["canon"] = df["PlayerName"].map(canonical_name)
    for col in ["PrefMode", "PrefBoost"]:
        if col not in df.columns:
            df[col] = pd.NA
    return df[["canon", "PrefGroup", "PrefMode", "PrefBoost"]].copy()


def _load_absences(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    if "PlayerName" not in df.columns:
        raise SystemExit("[fatal] absences.csv benötigt Spalte 'PlayerName']")
    for col in ["From", "To", "Reason", "Scope"]:
        if col not in df.columns:
            df[col] = ""

    _ensure_in_alliance_column(df, context="absences.csv")
    df = df[df["InAlliance"] == 1].copy()
    df["DisplayName"] = df["PlayerName"].fillna("").astype(str)
    df["canon"] = df["PlayerName"].map(canonical_name)

    def _parse_local(s: str) -> Optional[pd.Timestamp]:
        if pd.isna(s):
            return None
        if not isinstance(s, str):
            s = str(s)
        s = (s or "").strip()
        if not s:
            return None
        ts = pd.to_datetime(s, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.tz_localize(TZ) if ts.tzinfo is None else ts.tz_convert(TZ)

    df["From_ts"] = df["From"].map(_parse_local)
    df["To_ts"] = df["To"].map(_parse_local)
    df["Scope"] = df["Scope"].fillna("").astype(str)
    return df[
        [
            "DisplayName",
            "canon",
            "From",
            "To",
            "From_ts",
            "To_ts",
            "Reason",
            "InAlliance",
            "Scope",
        ]
    ].copy()


def _load_event_signups(path: str, to_canon) -> tuple[pd.DataFrame, Dict[str, int]]:
    """Load the next-event signup pool (manual confirmations for the upcoming roster).

    Semantik des CSV-Schemas ``PlayerName,Group,Role,Commitment,Source,Note``:
    - ``Commitment = hard``  → explizite Zusage („Teilnahme erbitten“ im Spiel
      oder direkte Rückmeldung). Diese Einträge bilden den kompletten Kandidaten-
      pool im Modus ``hard_signups_only`` und erzeugen forced slots, sofern der
      Spieler aktiv, in der Allianz und nicht abwesend ist.
    - ``Commitment = none``  → reine Info/Overlay, beeinflusst den Roster nicht.
    - ``Source`` dokumentiert den Kanal (z. B. ``ingame``, ``dm``, ``manual``),
      hat aber keine Logik-Auswirkung.
    """

    cols = ["PlayerName", "Group", "Role", "Commitment", "Source", "Note"]
    meta: Dict[str, int] = {
        "raw_rows": 0,
        "rows_with_playername": 0,
        "rows_with_canon": 0,
        "hard_commitments": 0,
    }
    try:
        df = pd.read_csv(path, dtype=str)
    except FileNotFoundError:
        print(f"[info] event signups: {path} fehlt – starte leer")
        return pd.DataFrame(columns=cols + ["RowNumber", "canon"]), meta
    except Exception as e:
        print(f"[warn] event signups: {path} nicht lesbar ({e}), starte leer")
        return pd.DataFrame(columns=cols + ["RowNumber", "canon"]), meta

    # Sämtliche Spaltennamen case-insensitive auf die erwarteten Header mappen.
    # Hintergrund: Admin-UI & Sheets können Header gelegentlich in lowercase
    # schreiben (commitment/source/note) → harte Zusagen gingen verloren.
    lower_to_expected = {c.lower(): c for c in cols}
    for col in list(df.columns):
        col_norm = str(col).strip().lower()
        if col_norm in lower_to_expected and lower_to_expected[col_norm] not in df.columns:
            df = df.rename(columns={col: lower_to_expected[col_norm]})

    meta["raw_rows"] = int(len(df))
    # Merke die ursprüngliche Zeilennummer (inkl. Header) für Diagnosezwecke.
    # Header = Zeile 1 → erste Datenzeile = 2.
    df["RowNumber"] = df.index + 2

    for col in cols:
        if col not in df.columns:
            df[col] = ""

    df = df[cols + ["RowNumber"]].copy()
    df["PlayerName"] = df["PlayerName"].fillna("").astype(str).str.strip()
    df = df[df["PlayerName"] != ""]
    meta["rows_with_playername"] = int(len(df))
    df["canon"] = df["PlayerName"].map(to_canon)
    meta["rows_with_canon"] = int(df["canon"].notna().sum())

    df["Group"] = df["Group"].fillna("").astype(str).str.strip().str.upper()
    df["Role"] = df["Role"].fillna("").astype(str).str.strip().str.title()
    df["Commitment"] = (
        df["Commitment"].fillna("none").astype(str).str.strip().str.lower().replace("", "none")
    )
    allowed_commitments = {"none", "hard"}
    df.loc[~df["Commitment"].isin(allowed_commitments), "Commitment"] = "none"
    meta["hard_commitments"] = int((df["Commitment"] == "hard").sum())
    df["Source"] = df["Source"].fillna("manual").astype(str).str.strip().replace("", "manual")
    df["Note"] = df["Note"].fillna("").astype(str)
    return df, meta


def _load_event_responses(path: str, to_canon) -> tuple[pd.DataFrame, Dict[str, int]]:
    """Load event-specific declines/no-responses for the next event.

    Schema (case-insensitive Header akzeptiert):
      PlayerName, Status, Source, Note

    Status-Normalisierung:
      - decline | declined | absage | no | cancel → decline
      - no_response | none | unanswered | n/a | missing → no_response
      Alle anderen Werte → ignoriert (Status=None).
    """

    cols = ["PlayerName", "Status", "Source", "Note"]
    meta: Dict[str, int] = {
        "raw_rows": 0,
        "rows_with_playername": 0,
        "rows_with_canon": 0,
        "declines": 0,
        "no_responses": 0,
    }

    try:
        df = pd.read_csv(path, dtype=str)
    except FileNotFoundError:
        print(f"[info] event responses: {path} fehlt – starte leer")
        return pd.DataFrame(columns=cols), meta
    except Exception as e:
        print(f"[warn] event responses: {path} nicht lesbar ({e}), starte leer")
        return pd.DataFrame(columns=cols), meta

    lower_to_expected = {c.lower(): c for c in cols}
    for col in list(df.columns):
        col_norm = str(col).strip().lower()
        if col_norm in lower_to_expected and lower_to_expected[col_norm] not in df.columns:
            df = df.rename(columns={col: lower_to_expected[col_norm]})

    meta["raw_rows"] = int(len(df))
    df["RowNumber"] = df.index + 2
    for col in cols:
        if col not in df.columns:
            df[col] = ""

    df = df[cols + ["RowNumber"]].copy()
    df["PlayerName"] = df["PlayerName"].fillna("").astype(str).str.strip()
    df = df[df["PlayerName"] != ""]
    meta["rows_with_playername"] = int(len(df))
    df["canon"] = df["PlayerName"].map(to_canon)
    meta["rows_with_canon"] = int(df["canon"].notna().sum())

    def _normalize_status(val: str) -> str:
        norm = (val or "").strip().lower()
        if norm in {"decline", "declined", "absage", "no", "cancel", "canceled", "cancelled"}:
            return "decline"
        if norm in {"no_response", "none", "unanswered", "n/a", "", "missing", "unknown"}:
            return "no_response"
        return ""

    df["Status"] = df["Status"].map(_normalize_status)
    meta["declines"] = int((df["Status"] == "decline").sum())
    meta["no_responses"] = int((df["Status"] == "no_response").sum())
    df["Source"] = df["Source"].fillna("manual_event_response").astype(str).str.strip().replace("", "manual_event_response")
    df["Note"] = df["Note"].fillna("").astype(str)
    df = df[df["Status"] != ""]
    return df, meta


def _normalize_for_match(value: str) -> str:
    """Normalisiert Namen für heuristische Alias-Erkennung."""
    if value is None:
        return ""
    norm = canonical_name(value)
    norm = norm.replace("-", " ").replace("_", " ")
    norm = norm.replace(" ", "")
    trans = str.maketrans({"0": "o", "1": "l"})
    norm = norm.translate(trans)
    return norm


def find_alias_suggestions(
    pool_df: pd.DataFrame,
    events_df: pd.DataFrame,
    alias_map: Dict[str, str],
) -> List[Dict[str, str]]:
    """Erzeugt Alias-Vorschläge für aktive Spieler ohne Event-Historie."""

    if pool_df.empty or events_df.empty:
        return []

    norm_to_events: Dict[str, set[str]] = {}
    event_display_map: Dict[str, str] = {}

    player_series = events_df.get("PlayerName")
    if player_series is None:
        return []

    for raw_name in player_series.dropna().astype(str):
        canon = canonical_name(raw_name)
        canon = alias_map.get(canon, canon)
        norm = _normalize_for_match(canon)
        if not norm:
            continue
        norm_to_events.setdefault(norm, set()).add(canon)
        event_display_map.setdefault(canon, raw_name)

    suggestions: List[Dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for row in pool_df.itertuples(index=False):
        if getattr(row, "InAlliance", getattr(row, "Active", 0)) != 1:
            continue
        events_seen = getattr(row, "events_seen", 0)
        try:
            events_seen_int = int(events_seen)
        except Exception:
            events_seen_int = 0
        if events_seen_int > 0:
            continue

        display_name = getattr(row, "DisplayName", getattr(row, "PlayerName", ""))
        if not display_name:
            continue

        canon_name = getattr(row, "canon", canonical_name(display_name))
        norm_display = _normalize_for_match(display_name)
        if not norm_display:
            continue

        matches = norm_to_events.get(norm_display)
        if not matches:
            continue

        for match_canon in sorted(matches):
            if match_canon == canon_name:
                continue
            key = (display_name, match_canon)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            suggestions.append(
                {
                    "DisplayName": display_name,
                    "EventName": event_display_map.get(match_canon, match_canon),
                    "Reason": "Normalized match (space/case/dash & 0↔o/1↔l)",
                }
            )
            break

    return suggestions


def _current_local_dt() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(TZ))


def _infer_next_event_ts(events_df: pd.DataFrame) -> tuple[pd.Timestamp, Dict[str, object]]:
    """Return a best-effort timestamp for the next DS event.

    Heuristik:
    - Nutze das maximale Event-Datum aus der Historie (EventID → Datum via
      parse_event_date) und addiere das häufigste Intervall zwischen Events.
    - Fallback auf 7 Tage, falls keine Intervalle vorhanden sind.
    - Immer in lokale Zeitzone konvertieren.
    """

    parsed_dates = pd.to_datetime(
        events_df["EventID"].map(parse_event_date), errors="coerce", utc=True
    )
    df = pd.DataFrame({"event_id": events_df["EventID"], "event_dt": parsed_dates})
    df = df.dropna(subset=["event_dt"]).drop_duplicates(subset=["event_id"])
    if df.empty:
        ts = _current_local_dt()
        return ts, {"source": "fallback_now", "last_event_id": None, "last_event_date": None}

    df = df.sort_values("event_dt")
    last_row = df.iloc[-1]
    unique_dates = df["event_dt"].drop_duplicates().reset_index(drop=True)
    if len(unique_dates) >= 2:
        deltas = unique_dates.diff().dropna()
        mode_delta = deltas.mode()
        delta = mode_delta.iloc[0] if not mode_delta.empty else deltas.median()
    else:
        delta = pd.Timedelta(days=7)
    if not isinstance(delta, pd.Timedelta) or delta <= pd.Timedelta(0):
        delta = pd.Timedelta(days=7)

    next_event_ts = (last_row.event_dt + delta).tz_convert(TZ)
    meta = {
        "source": "history_plus_interval",
        "last_event_id": str(last_row.event_id),
        "last_event_date": last_row.event_dt.isoformat(),
        "interval_days": float(delta / pd.Timedelta(days=1)),
    }
    return next_event_ts, meta


def _mark_absences_for_next_event(abs_df: pd.DataFrame, *, reference_ts: pd.Timestamp) -> pd.DataFrame:
    """Annotate absences with a stable "next event" rule.

    Regel (explizit dokumentiert, da Admin-UI das genauso kommunizieren soll):
    - Falls die optionale Spalte ``Scope`` (case-insensitive) den Wert
      ``next_event`` trägt → Absenz gilt immer für das nächste DS-Event.
    - Falls weder ``From`` noch ``To`` gesetzt sind → ebenfalls "next_event"
      (Kurz-Notiz ohne Datumsbindung).
    - Ansonsten gilt die Datums-Spanne relativ zum Build-Zeitpunkt
      ``reference_ts`` (lokale Zeitzone): Von/To werden als inklusiv gewertet.
    """

    df = abs_df.copy()
    df["scope_norm"] = df["Scope"].fillna("").astype(str).str.strip().str.lower()
    scope_next = df["scope_norm"] == "next_event"

    from_blank = df["From"].fillna("").astype(str).str.strip() == ""
    to_blank = df["To"].fillna("").astype(str).str.strip() == ""
    scope_empty = from_blank & to_blank

    def _range_active(row) -> bool:
        f, t = row["From_ts"], row["To_ts"]
        if f is not None and pd.notna(f) and reference_ts < f:
            return False
        if t is not None and pd.notna(t) and reference_ts > t:
            return False
        return True

    in_range = df.apply(_range_active, axis=1)
    df["is_absent_next_event"] = scope_next | scope_empty | in_range
    return df


def _init_absence_payloads(absences_path: str, *, next_event_ts: pd.Timestamp, next_event_meta: Dict[str, object]) -> tuple[Dict[str, object], Dict[str, object]]:
    """Build empty payload dictionaries for absence reporting.

    These payloads are populated later once absences have been loaded and
    filtered. Keeping the initialization centralized makes the structure of the
    expected outputs explicit without altering any runtime behaviour.
    """

    absences_payload = {
        "schema": 1,
        "source": str(Path(absences_path)) if absences_path else "",
        "total_entries": 0,
        "active_entries": 0,
        "players": [],
    }

    absence_debug = {
        "schema": 2,
        "source": str(Path(absences_path)) if absences_path else "",
        "raw_count": 0,
        "active_for_next_event": 0,
        "file_entries": [],
        "next_event_absences": [],
        "stats": {
            "file_entries": 0,
            "active_for_next_event": 0,
            "unique_active_players": 0,
        },
        "reference_event": {
            "event_date": next_event_ts.isoformat(),
            "source": next_event_meta.get("source"),
            "last_event_id": next_event_meta.get("last_event_id"),
            "last_event_date": next_event_meta.get("last_event_date"),
        },
    }

    return absences_payload, absence_debug


def _init_event_response_payload(event_responses_path: str) -> Dict[str, object]:
    """Return the default payload structure for event responses."""

    return {
        "schema": 1,
        "scope": "next_event",
        "source": str(Path(event_responses_path)) if event_responses_path else "",
        "file_entries": [],
        "stats": {
            "file_entries": 0,
            "declines": 0,
            "no_responses": 0,
            "applied_entries": 0,
            "ignored_entries": 0,
            "removed_from_pool": 0,
            "penalties": 0,
        },
        "removed_from_pool": [],
        "penalty_applied": [],
    }


def _load_primary_data(args) -> Dict[str, object]:
    """Load all core inputs (events, alliance, aliases, preferences, absences)."""

    norm_patterns = _normalize_event_patterns(args.events)
    events_df = _load_events(norm_patterns)
    next_event_ts, next_event_meta = _infer_next_event_ts(events_df)
    alliance_df = _load_alliance(args.alliance)

    alias_map: Dict[str, str] = {}
    if args.aliases:
        try:
            alias_map = load_alias_map(args.aliases)
            print(f"[ok] aliases loaded: {len(alias_map)} Regeln")
        except AliasResolutionError as e:
            print(f"[warn] aliases konnten nicht geladen werden: {e}")
        except Exception as e:
            print(f"[warn] aliases konnten nicht geladen werden: {e}")

    def to_canon(value):
        if value is None or pd.isna(value):
            return pd.NA
        base = canonical_name(value)
        return alias_map.get(base, base)

    prefs_df = None
    if args.preferences:
        try:
            prefs_df = _load_preferences(args.preferences)
            print(f"[ok] preferences loaded: {len(prefs_df)} Einträge")
        except Exception as e:
            print(f"[warn] preferences nicht nutzbar: {e}")

    abs_df = None
    if args.absences:
        abs_path = Path(args.absences)
        if not abs_path.exists():
            print(f"[info] absences: {abs_path} fehlt – überspringe")
        else:
            try:
                abs_df = _load_absences(args.absences)
                abs_df["canon"] = abs_df["canon"].map(to_canon)
                abs_df = abs_df[abs_df["canon"].notna()].copy()
                print(f"[ok] absences loaded: {len(abs_df)} Einträge")
            except Exception as e:
                print(f"[warn] absences nicht nutzbar: {e}")

    return {
        "events_df": events_df,
        "next_event_ts": next_event_ts,
        "next_event_meta": next_event_meta,
        "alliance_df": alliance_df,
        "alias_map": alias_map,
        "to_canon": to_canon,
        "prefs_df": prefs_df,
        "abs_df": abs_df,
    }


def _load_event_overlays(args, to_canon) -> Dict[str, object]:
    """Load signups and responses for the next event."""

    event_signups_df, event_signup_load_meta = _load_event_signups(args.event_signups, to_canon)
    print(
        "[info] event signups geladen: "
        f"{len(event_signups_df)} Einträge (Pool für nächstes Event) – "
        f"raw={event_signup_load_meta.get('raw_rows', 0)}, "
        f"with_name={event_signup_load_meta.get('rows_with_playername', 0)}, "
        f"canonical={event_signup_load_meta.get('rows_with_canon', 0)}, "
        f"hard={event_signup_load_meta.get('hard_commitments', 0)}"
    )

    event_responses_df, event_response_meta = _load_event_responses(args.event_responses, to_canon)
    print(
        "[info] event responses geladen: "
        f"{len(event_responses_df)} Einträge (Absagen/No-Response) – "
        f"raw={event_response_meta.get('raw_rows', 0)}, "
        f"with_name={event_response_meta.get('rows_with_playername', 0)}, "
        f"canonical={event_response_meta.get('rows_with_canon', 0)}, "
        f"declines={event_response_meta.get('declines', 0)}, "
        f"no_response={event_response_meta.get('no_responses', 0)}"
    )

    return {
        "event_signups_df": event_signups_df,
        "event_responses_df": event_responses_df,
        "event_signup_load_meta": event_signup_load_meta,
        "event_response_meta": event_response_meta,
    }


# --------------------------
# Writer
# --------------------------
def _write_outputs(out_dir: Path, roster_df: pd.DataFrame, json_payload: Dict):
    out_dir.mkdir(parents=True, exist_ok=True)
    latest_dirs = [Path("out"), Path("docs/out")]
    for latest_dir in latest_dirs:
        latest_dir.mkdir(parents=True, exist_ok=True)

    csv_cols = [
        "PlayerName",
        "Group",
        "Role",
        "NoShowOverall",
        "NoShowRolling",
        "AttendProb",
        "risk_penalty",
    ]
    for latest_dir in latest_dirs:
        roster_df[csv_cols].to_csv(latest_dir / "latest.csv", index=False)
        (latest_dir / "latest.json").write_text(
            json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    (out_dir / "roster.csv").write_text((roster_df[csv_cols]).to_csv(index=False), encoding="utf-8")
    (out_dir / "roster.json").write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "[ok] wrote "
        + ", ".join(str(path / "latest.csv") for path in latest_dirs)
        + " and "
        + ", ".join(str(path / "latest.json") for path in latest_dirs)
    )
    print(f"[ok] wrote {out_dir/'roster.csv'} and {out_dir/'roster.json'}")


# --------------------------
# Main
# --------------------------
def main():
    ap = argparse.ArgumentParser(description="Deterministischer Roster-Builder (A/B: 20/10)")
    ap.add_argument("--events", nargs="+", required=True, help="Glob-Pattern(s) für Event-CSV(s), z. B. data/*.csv (multiline erlaubt)")
    ap.add_argument("--alliance", required=True, help="Pfad zu data/alliance.csv")
    ap.add_argument("--aliases", default="", help="Pfad zu data/aliases.csv (optional)")
    ap.add_argument(
        "--absences",
        default="data/absences.csv",
        help="Pfad zu data/absences.csv (optional)",
    )
    ap.add_argument("--preferences", default="", help="Pfad zu data/preferences.csv (optional)")
    ap.add_argument(
        "--event-signups",
        default="data/event_signups_next.csv",
        help="Pfad zum Zusage-Pool für das nächste Event (ohne EventID-Spalte)",
    )
    ap.add_argument(
        "--event-responses",
        default="data/event_responses_next.csv",
        help="Pfad zu event-spezifischen Absagen/No-Responses für das nächste Event",
    )
    ap.add_argument("--half-life-days", type=float, default=90.0, help="Halbwertszeit für Rolling-Metriken (Tage)")
    ap.add_argument("--out", default="out", help="Ausgabeverzeichnis für Run-Artefakte (zusätzlich zu out/latest.*)")
    args = ap.parse_args()

    cfg = get_config()
    attendance_config, attendance_config_meta = load_attendance_config()
    callup_config, callup_config_meta = load_callup_config()
    callup_min_attend_prob = min(max(float(callup_config.callup_min_attend_prob), 0.0), 1.0)
    out_dir = Path(args.out)

    primary_data = _load_primary_data(args)
    events_df = primary_data["events_df"]
    next_event_ts = primary_data["next_event_ts"]
    next_event_meta = primary_data["next_event_meta"]
    alliance_df = primary_data["alliance_df"]
    alias_map = primary_data["alias_map"]
    to_canon = primary_data["to_canon"]
    prefs_df = primary_data["prefs_df"]
    abs_df = primary_data["abs_df"]

    absences_payload, absence_debug = _init_absence_payloads(
        args.absences, next_event_ts=next_event_ts, next_event_meta=next_event_meta
    )
    event_responses_payload: Dict[str, object] = _init_event_response_payload(args.event_responses)
    active_abs_meta: Dict[str, Dict[str, str]] = {}
    absent_now: set[str] = set()
    absence_conflicts: List[Dict] = []
    event_response_conflicts: List[Dict] = []

    overlays = _load_event_overlays(args, to_canon)
    event_signups_df = overlays["event_signups_df"]
    event_responses_df = overlays["event_responses_df"]
    event_signup_load_meta = overlays["event_signup_load_meta"]
    event_response_meta = overlays["event_response_meta"]

    # 2) Metriken berechnen
    role_probs = compute_role_probs(
        events_df,
        alias_map=alias_map,          # deine korrigierte stats.py unterstützt das
        half_life_days=args.half_life_days,
    )

    role_probs["canon"] = role_probs["PlayerName"].map(to_canon)

    alliance_df["canon"] = alliance_df["DisplayName"].map(to_canon)

    hist = compute_player_history(
        events_df,
        alias_map=alias_map,
        half_life_days=args.half_life_days,
    )
    hist["canon"] = hist["PlayerName"].map(to_canon)

    # 3) Allianz joinen (nur InAlliance==1 als Kandidaten)
    pool = alliance_df.merge(
        role_probs.drop(columns=["PlayerName"], errors="ignore"),
        on="canon",
        how="left",
    )

    pool = pool[pool["InAlliance"] == 1].copy()

    # Separate Preferences (falls vorhanden) haben Vorrang
    if prefs_df is not None and not prefs_df.empty:
        pool = pool.drop(columns=["PrefGroup", "PrefMode", "PrefBoost"])
        pool = pool.merge(prefs_df, on="canon", how="left")

    # 4) Abwesenheiten (nächstes Event) filtern
    if abs_df is not None and not abs_df.empty:
        now_ts = _current_local_dt()
        abs_df = _mark_absences_for_next_event(abs_df, reference_ts=next_event_ts)

        absences_payload["players"] = [
            {
                "name": getattr(row, "DisplayName", ""),
                "canonical": getattr(row, "canon", pd.NA),
                "reason": getattr(row, "Reason", "") or "",
                "scope": getattr(row, "scope_norm", "") or "",  # vgl. _mark_absences_for_next_event
                "from": getattr(row, "From", "") or "",
                "to": getattr(row, "To", "") or "",
                "in_alliance": int(getattr(row, "InAlliance", 0)),
                "is_active_next_event": bool(getattr(row, "is_absent_next_event", False)),
            }
            for row in abs_df.itertuples(index=False)
        ]
        absences_payload["total_entries"] = int(len(abs_df))
        absences_payload["active_entries"] = int(abs_df["is_absent_next_event"].sum())

        absence_debug["raw_count"] = int(len(abs_df))
        absence_debug["active_for_next_event"] = int(abs_df["is_absent_next_event"].sum())
        absence_debug["file_entries"] = []
        aggregated_absences: Dict[str, Dict[str, object]] = {}
        active_abs_meta: Dict[str, Dict[str, str]] = {}
        for row in abs_df.itertuples(index=False):
            scope_norm = getattr(row, "scope_norm", "") or ""
            scope_label = scope_norm or ("open_range" if ((getattr(row, "From", "") or "") == "" and (getattr(row, "To", "") or "") == "") else "date_range")
            canon_val = getattr(row, "canon", pd.NA)
            is_active = bool(getattr(row, "is_absent_next_event", False))
            if is_active and canon_val is not pd.NA and str(canon_val) not in active_abs_meta:
                active_abs_meta[str(canon_val)] = {
                    "reason": getattr(row, "Reason", "") or "",
                    "from": getattr(row, "From", "") or "",
                    "to": getattr(row, "To", "") or "",
                    "scope": scope_norm,
                }
            from_val = getattr(row, "From", "") or ""
            to_val = getattr(row, "To", "") or ""
            reason_val = getattr(row, "Reason", "") or ""
            file_entry = {
                "canonical": canon_val,
                "display": getattr(row, "DisplayName", "") or "",
                "reason": reason_val,
                "scope": scope_label,
                "source": str(Path(args.absences)) if args.absences else "",
                "from": from_val,
                "to": to_val,
                "is_absent_next_event": is_active,
            }
            absence_debug["file_entries"].append(file_entry)

            canon_key = None
            if canon_val is not pd.NA and pd.notna(canon_val):
                canon_key = str(canon_val)

            if is_active and canon_key:
                agg_entry = aggregated_absences.setdefault(
                    canon_key,
                    {
                        "canonical": canon_key,
                        "display": getattr(row, "DisplayName", "") or canon_key,
                        "active": True,
                        "ranges": [],
                        "in_alliance": bool(getattr(row, "InAlliance", 0)),
                    },
                )
                agg_entry["display"] = getattr(row, "DisplayName", "") or agg_entry["display"]
                agg_entry["in_alliance"] = bool(getattr(row, "InAlliance", 0))
                agg_entry.setdefault("ranges", []).append(
                    {
                        "from": from_val,
                        "to": to_val,
                        "reason": reason_val,
                        "scope": scope_label,
                    }
                )

        absent_now = set(abs_df.loc[abs_df["is_absent_next_event"], "canon"].tolist())
        before = len(pool)
        pool = pool[~pool["canon"].isin(absent_now)].copy()
        print(
            "[info] absences filter: "
            f"{before - len(pool)} ausgeschlossen (ref_event={next_event_ts.isoformat()}, now={now_ts.isoformat()}, raw={absence_debug['raw_count']}, active={absence_debug['active_for_next_event']})"
        )

        agg_list = sorted(aggregated_absences.values(), key=lambda x: (x.get("display") or x.get("canonical") or ""))
        absence_debug["next_event_absences"] = agg_list
        absence_debug["stats"] = {
            "file_entries": absence_debug["raw_count"],
            "active_for_next_event": absence_debug["active_for_next_event"],
            "unique_active_players": len(agg_list),
        }
        absence_debug["players"] = absence_debug["file_entries"]

    response_penalties: Dict[str, float] = {}
    response_by_canon: Dict[str, Dict[str, object]] = {}
    decline_canons: set[str] = set()
    noresp_canons: set[str] = set()
    if not event_responses_df.empty:
        response_penalty_value = 0.15
        players_lookup = {
            str(getattr(row, "canon", "")): getattr(row, "DisplayName", "")
            for row in alliance_df.itertuples(index=False)
        }
        for row in event_responses_df.itertuples(index=False):
            canon_val = getattr(row, "canon", pd.NA)
            status_val = getattr(row, "Status", "") or ""
            entry = {
                "canonical": canon_val,
                "display": getattr(row, "PlayerName", ""),
                "status": status_val,
                "source": getattr(row, "Source", ""),
                "note": getattr(row, "Note", ""),
                "row_index": int(getattr(row, "RowNumber", 0)),
            }
            event_responses_payload["file_entries"].append(entry)
            event_responses_payload["stats"]["file_entries"] += 1

            if pd.isna(canon_val):
                event_responses_payload["stats"]["ignored_entries"] += 1
                continue
            canon_key = str(canon_val)
            response_by_canon[canon_key] = entry
            event_responses_payload["stats"]["applied_entries"] += 1
            if status_val == "decline":
                decline_canons.add(canon_key)
                event_responses_payload["stats"]["declines"] += 1
            elif status_val == "no_response":
                noresp_canons.add(canon_key)
                event_responses_payload["stats"]["no_responses"] += 1

        if decline_canons:
            before = len(pool)
            pool = pool[~pool["canon"].isin(decline_canons)].copy()
            removed = before - len(pool)
            event_responses_payload["stats"]["removed_from_pool"] = removed
            for canon_val in sorted(decline_canons):
                event_responses_payload["removed_from_pool"].append(
                    {
                        "canonical": canon_val,
                        "display": players_lookup.get(canon_val, canon_val),
                        "status": "decline",
                    }
                )

        if noresp_canons:
            for canon_val in noresp_canons:
                response_penalties[canon_val] = response_penalty_value
                event_responses_payload["penalty_applied"].append(
                    {
                        "canonical": canon_val,
                        "display": players_lookup.get(canon_val, canon_val),
                        "status": "no_response",
                        "risk_penalty": response_penalty_value,
                    }
                )
            event_responses_payload["stats"]["penalties"] = len(noresp_canons)
    event_responses_payload["stats"]["file_entries"] = int(
        event_response_meta.get("raw_rows", len(event_responses_df))
    )

    hist_cols = [
        "canon",
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
    pool = pool.merge(hist[hist_cols], on="canon", how="left")

    pool["assignments_total"] = (
        pd.to_numeric(pool["assignments_total"], errors="coerce")
        .fillna(0)
        .astype(int)
    )
    pool["noshows_total"] = (
        pd.to_numeric(pool["noshows_total"], errors="coerce")
        .fillna(0)
        .astype(int)
    )
    pool["events_seen"] = pool["assignments_total"]
    pool["noshow_count"] = pool["noshows_total"]

    pool["w_assignments_total"] = pd.to_numeric(
        pool["w_assignments_total"], errors="coerce"
    ).fillna(0.0)
    pool["noshow_rate"] = pd.to_numeric(pool["noshow_rate"], errors="coerce")
    pool["w_noshow_rate"] = pd.to_numeric(pool["w_noshow_rate"], errors="coerce")

    observed_series = pool["w_noshow_rate"].where(
        pool["w_assignments_total"] > 0, pool["noshow_rate"]
    )
    observed_rates = [
        float(v)
        for v in observed_series.loc[pool["events_seen"] > 0].dropna().tolist()
    ]
    p0 = compute_team_prior(
        observed_rates,
        winsor=bool(cfg.WINSORIZE),
        fallback=float(cfg.PRIOR_FALLBACK),
    )
    prior_with_pad = min(max(p0 + float(cfg.PRIOR_PAD), 0.0), 1.0)

    pool["p_start"] = pd.to_numeric(pool["p_start"], errors="coerce")
    pool["p_sub"] = pd.to_numeric(pool["p_sub"], errors="coerce")

    if cfg.EB_ENABLE:
        eb_p_hat_vals: List[float] = []
        eb_sigma_vals: List[float] = []
        risk_vals: List[float] = []
        for row in pool.itertuples(index=False):
            s = getattr(row, "noshow_count", 0)
            n = getattr(row, "events_seen", 0)
            p_hat, sigma = eb_rate(s, n, p0, cfg.EB_N0)
            eb_p_hat_vals.append(p_hat)
            eb_sigma_vals.append(sigma)
            risk_vals.append(cfg.EB_LAMBDA * sigma)
    else:
        eb_p_hat_vals = [float("nan")] * len(pool)
        eb_sigma_vals = [float("nan")] * len(pool)
        risk_vals = [0.0] * len(pool)

    pool["eb_p_hat"] = pd.Series(eb_p_hat_vals, index=pool.index, dtype="float64")
    pool["eb_sigma"] = pd.Series(eb_sigma_vals, index=pool.index, dtype="float64")
    pool["risk_penalty"] = (
        pd.Series(risk_vals, index=pool.index, dtype="float64").fillna(0.0)
    )
    pool["risk_penalty"] = pool["risk_penalty"].clip(lower=0.0)
    if response_penalties:
        penalty_series = pool["canon"].map(lambda c: response_penalties.get(str(c), 0.0))
        pool["risk_penalty"] = (pool["risk_penalty"] + penalty_series.fillna(0.0)).clip(lower=0.0)

    no_data_mask = pool["events_seen"] <= 0
    pool.loc[no_data_mask, "p_start"] = p0
    pool.loc[no_data_mask, "p_sub"] = p0
    pool["p_start"] = pool["p_start"].fillna(p0).clip(0.0, 1.0)
    pool["p_sub"] = pool["p_sub"].fillna(p0).clip(0.0, 1.0)

    base_show = (1.0 - pool["w_noshow_rate"]).where(pool["w_assignments_total"] > 0, 1.0 - prior_with_pad)
    base_show = base_show.fillna(1.0 - prior_with_pad)
    if cfg.EB_ENABLE:
        base_show = (1.0 - pool["eb_p_hat"]).where(pd.notna(pool["eb_p_hat"]), base_show)
    pool["attend_prob_raw"] = base_show.clip(0.0, 1.0)
    pool["attend_prob"] = (pool["attend_prob_raw"] - pool["risk_penalty"]).clip(0.0, 1.0)

    if noresp_canons:
        nr_factor = min(
            max(float(attendance_config.no_response_multiplier), 0.0), 1.0
        )
        nr_mask = pool["canon"].isin(noresp_canons)
        pool.loc[nr_mask, "attend_prob"] = (pool.loc[nr_mask, "attend_prob"] * nr_factor).clip(0.0, 1.0)

    hard_signups_only = bool(getattr(cfg, "HARD_SIGNUPS_ONLY", False))
    hard_signup_canons: set[str] = {
        str(c).strip()
        for c in event_signups_df.loc[event_signups_df["Commitment"] == "hard", "canon"].dropna().tolist()
        if str(c).strip()
    }
    builder_pool = pool.copy()
    builder_pool_stats: Dict[str, object] = {
        "hard_signups_only": hard_signups_only,
        "builder_candidates_total": int(len(builder_pool)),
        "hard_commitments_total": int(len(hard_signup_canons)),
        "filtered_out": 0,
    }
    if hard_signups_only:
        before = len(builder_pool)
        builder_pool = builder_pool[builder_pool["canon"].astype(str).isin(hard_signup_canons)].copy()
        filtered_out = before - len(builder_pool)
        builder_pool_stats["builder_candidates_total"] = int(len(builder_pool))
        builder_pool_stats["filtered_out"] = int(filtered_out)
        print(
            "[info] hard_signups_only aktiv: "
            f"{len(builder_pool)} Kandidaten (von {before}, filtered={filtered_out})"
        )

    alias_suggestions = find_alias_suggestions(pool, events_df, alias_map)
    alias_out_path = Path("out") / "alias_suggestions.csv"
    if alias_suggestions:
        alias_out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(alias_suggestions, columns=["DisplayName", "EventName", "Reason"]).to_csv(
            alias_out_path, index=False
        )
        for suggestion in alias_suggestions:
            print(
                "::warning:: Alias-Hinweis: "
                f"{suggestion['DisplayName']} → {suggestion['EventName']} ({suggestion['Reason']})"
            )
        print(f"[info] Alias-Hinweise gespeichert: {alias_out_path}")
    else:
        print("::notice:: Keine Alias-Hinweise gefunden (alle aktiven Spieler haben Historie).")

    # 5) Harte Zusagen → Forced-Slots vorbereiten
    pool_idx = builder_pool.set_index("canon")
    in_alliance_set = set(alliance_df.loc[alliance_df["InAlliance"] == 1, "canon"])

    forced_signups: List[Dict] = []
    invalid_forced_signups: List[Dict] = []
    signup_file_entries: List[Dict[str, object]] = []
    capacities_remaining = {g: {"Start": STARTERS_PER_GROUP, "Ersatz": SUBS_PER_GROUP} for g in GROUPS}

    hard_commitment_mask = event_signups_df["Commitment"] == "hard"
    hard_signup_total = int(hard_commitment_mask.sum())
    # Commitment "hard" ist die einzige Quelle für Fixplätze – Source dient nur als Dokumentation.
    seen_forced: set[str] = set()
    hard_commit_player_labels: List[str] = []
    forced_count_snapshot = {g: {"Start": 0, "Ersatz": 0} for g in GROUPS}

    def _choose_group(canon: str, signup_group: str, pref_group: Optional[str]) -> str:
        # Explizite Wahl aus event_signups_next.csv hat Vorrang, auch wenn die Gruppe
        # bereits überbucht ist. Erst wenn keine gültige Gruppe gesetzt ist, fallen
        # wir auf PrefGroup bzw. Balancing zurück.
        if signup_group in GROUPS:
            return signup_group

        desired = []
        if pref_group in GROUPS:
            desired.append(pref_group)
        # Balancing-Heuristik: wähle die Gruppe mit den meisten Rest-Slots
        if not desired:
            desired = GROUPS
        return max(
            desired,
            key=lambda g: (
                capacities_remaining[g]["Start"] + capacities_remaining[g]["Ersatz"],
                -GROUPS.index(g),
            ),
        )

    def _choose_role(target_group: str, signup_role: str) -> str:
        role_norm = signup_role if signup_role in {"Start", "Ersatz"} else None
        if role_norm is None:
            # Start bevorzugen, sonst Balancing
            start_slots = capacities_remaining[target_group]["Start"]
            sub_slots = capacities_remaining[target_group]["Ersatz"]
            if start_slots >= sub_slots:
                role_norm = "Start"
            else:
                role_norm = "Ersatz"
        return role_norm

    for row in event_signups_df.itertuples(index=False):
        display = getattr(row, "PlayerName", "") or ""
        group_pref = (getattr(row, "Group", "") or "").strip().upper()
        role_pref = (getattr(row, "Role", "") or "").strip().title()
        commitment = (getattr(row, "Commitment", "") or "none").strip().lower() or "none"
        source = (getattr(row, "Source", "") or "manual").strip()
        note = (getattr(row, "Note", "") or "").strip()
        canon_val = getattr(row, "canon", pd.NA)
        canon = None if pd.isna(canon_val) or not str(canon_val).strip() else str(canon_val)
        row_idx_val = getattr(row, "RowNumber", None)
        try:
            row_index = int(row_idx_val)
        except (TypeError, ValueError):
            row_index = None

        row_debug = {
            "row_index": row_index,
            "player": display or canon,
            "canon": canon,
            "group_pref": group_pref or None,
            "role_pref": role_pref or None,
            "commitment": commitment,
            "source": source,
            "note": note,
            "in_alliance": bool(canon and canon in in_alliance_set),
            "in_player_pool": bool(canon and canon in pool_idx.index),
            "is_absent_next_event": bool(canon and canon in absent_now),
        }

        if commitment == "hard":
            hard_commit_player_labels.append(display or canon or f"row {row_index or '?'}")
        if commitment != "hard":
            row_debug["status"] = "info_only"
            signup_file_entries.append(row_debug)
            continue

        if not canon:
            invalid_forced_signups.append({"player": display, "reason": "unknown_player"})
            row_debug.update({"status": "invalid", "reason": "unknown_player"})
            signup_file_entries.append(row_debug)
            continue
        if canon in seen_forced:
            invalid_forced_signups.append({"player": display, "canon": canon, "reason": "duplicate"})
            row_debug.update({"status": "invalid", "reason": "duplicate"})
            signup_file_entries.append(row_debug)
            continue
        if canon not in in_alliance_set:
            invalid_forced_signups.append({"player": display, "canon": canon, "reason": "not_in_alliance"})
            row_debug.update({"status": "invalid", "reason": "not_in_alliance"})
            signup_file_entries.append(row_debug)
            continue
        if canon in absent_now:
            invalid_forced_signups.append({"player": display, "canon": canon, "reason": "absent"})
            row_debug.update({"status": "invalid", "reason": "absent"})
            signup_file_entries.append(row_debug)
            continue
        if canon not in pool_idx.index:
            invalid_forced_signups.append({"player": display, "canon": canon, "reason": "inactive_or_filtered"})
            row_debug.update({"status": "invalid", "reason": "inactive_or_filtered"})
            signup_file_entries.append(row_debug)
            continue

        pref_group_val = pool_idx.loc[canon].get("PrefGroup") if canon in pool_idx.index else pd.NA
        pref_group = None if pd.isna(pref_group_val) else str(pref_group_val).strip().upper()
        row_debug["pref_group_in_pool"] = pref_group
        target_group = _choose_group(canon, group_pref, pref_group)
        target_role = _choose_role(target_group, role_pref)

        capacities_remaining[target_group][target_role] -= 1
        overbooked = capacities_remaining[target_group][target_role] < 0
        seen_forced.add(canon)
        forced_entry = {
            "player": display or canon,
            "canon": canon,
            "group": target_group,
            "role": target_role,
            "source": source,
            "note": note,
            "commitment": "hard",
            "overbooked": overbooked,
        }
        forced_signups.append(forced_entry)
        row_debug.update(
            {
                "status": "forced",
                "resolved_group": target_group,
                "resolved_role": target_role,
                "overbooked": overbooked,
            }
        )
        signup_file_entries.append(row_debug)
        forced_count_snapshot[target_group][target_role] += 1

    if hard_commit_player_labels:
        label_preview = ", ".join(hard_commit_player_labels)
        print(
            "[info] hard commitments im Zusage-Pool: "
            f"{hard_signup_total} Spieler → {label_preview}"
        )

    overbooked_forced_signups: List[Dict] = []
    for g in GROUPS:
        for r in ["Start", "Ersatz"]:
            remaining = capacities_remaining[g][r]
            if remaining < 0:
                overbooked_forced_signups.append(
                    {
                        "group": g,
                        "role": r,
                        "excess_forced": abs(remaining),
                        "capacity": STARTERS_PER_GROUP if r == "Start" else SUBS_PER_GROUP,
                    }
                )
                capacities_remaining[g][r] = 0  # Optimizer darf nicht weiter ins Minus laufen

    target_caps_by_group_role = {
        g: {r: capacities_remaining[g][r] + forced_count_snapshot[g][r] for r in ["Start", "Ersatz"]}
        for g in GROUPS
    }

    if seen_forced:
        hard_floor = min(max(float(attendance_config.hard_commit_floor), 0.0), 1.0)
        hard_mask = pool["canon"].isin(seen_forced)
        pool.loc[hard_mask, "attend_prob"] = pool.loc[hard_mask, "attend_prob"].clip(lower=hard_floor)

    next_event_status: Dict[str, str] = {}
    signup_canons = set(
        str(c)
        for c in event_signups_df.get("canon", pd.Series(dtype=object)).dropna().tolist()
    )
    for canon_val in pool["canon"].dropna().astype(str).tolist():
        if canon_val in signup_canons:
            next_event_status[canon_val] = "signup"
        else:
            next_event_status.setdefault(canon_val, "open")
    for canon_val in noresp_canons:
        next_event_status[canon_val] = "no_response"
    for canon_val in decline_canons:
        next_event_status[canon_val] = "decline"
    for canon_val in seen_forced:
        next_event_status[canon_val] = "hard_commitment"

    # 6) Input für Builder (nur Rest-Slots)
    pool_for_builder = builder_pool[~builder_pool["canon"].isin(seen_forced)].copy()
    # Team-Logik:
    #  - Team A Starter: immer voll besetzen (kein Attend-Filter)
    #  - Team B Starter: nur Spieler über der globalen Attend-Schwelle
    #  - Bänke: bevorzugt Spieler über der Schwelle, Rest darf leer bleiben
    min_start_thresholds = {"A": None, "B": callup_min_attend_prob}
    min_bench_thresholds = {g: callup_min_attend_prob for g in GROUPS}
    probs_for_builder = pd.DataFrame({
        "PlayerName": pool_for_builder["canon"],
        "attend_prob": pool_for_builder["attend_prob"].fillna(1.0 - prior_with_pad),
        "p_start": pool_for_builder["attend_prob"].fillna(1.0 - prior_with_pad),
        "p_sub": pool_for_builder["attend_prob"].fillna(1.0 - prior_with_pad),
        "PrefGroup": pool_for_builder.get("PrefGroup", pd.Series([pd.NA]*len(pool_for_builder))),
        "PrefMode": pool_for_builder.get("PrefMode", pd.Series([pd.NA]*len(pool_for_builder))),
        "PrefBoost": pool_for_builder.get("PrefBoost", pd.Series([pd.NA]*len(pool_for_builder))),
        "events_seen": pool_for_builder["events_seen"],
        "risk_penalty": pool_for_builder["risk_penalty"],
        "shows_total": pool_for_builder.get("shows_total", pd.Series([pd.NA] * len(pool_for_builder))),
        "noshows_total": pool_for_builder.get("noshows_total", pd.Series([pd.NA] * len(pool_for_builder))),
        "noshow_rate": pool_for_builder.get("noshow_rate", pd.Series([pd.NA] * len(pool_for_builder))),
        "w_noshow_rate": pool_for_builder.get("w_noshow_rate", pd.Series([pd.NA] * len(pool_for_builder))),
        "attend_prob_raw": pool_for_builder.get("attend_prob_raw", pd.Series([pd.NA] * len(pool_for_builder))),
        "eb_p_hat": pool_for_builder.get("eb_p_hat", pd.Series([pd.NA] * len(pool_for_builder))),
        "eb_sigma": pool_for_builder.get("eb_sigma", pd.Series([pd.NA] * len(pool_for_builder))),
        "eb_prior_p0": pd.Series([p0] * len(pool_for_builder), index=pool_for_builder.index),
        "eb_n0": pd.Series([cfg.EB_N0] * len(pool_for_builder), index=pool_for_builder.index),
        "is_low_n": pool_for_builder["events_seen"] <= callup_config.low_n_max_events,
    })

    # 7) Roster bauen
    min_b_starters_cfg = callup_config.min_b_starters if callup_config.min_b_starters else MIN_B_STARTERS
    roster = build_deterministic_roster(
        probs_for_builder,
        forced_assignments=[
            {"PlayerName": f["canon"], "Group": f["group"], "Role": f["role"]}
            for f in forced_signups
        ],
        capacities_by_group_role=capacities_remaining,
        min_attend_start=min_start_thresholds,
        min_attend_sub=min_bench_thresholds,
        min_b_starters=min_b_starters_cfg,
        allow_unfilled=True,
    )  # PlayerName = canon

    # 8) Anzeige + Kennzahlen
    disp_map = dict(zip(alliance_df["canon"], alliance_df["DisplayName"]))
    roster["DisplayName"] = roster["PlayerName"].map(lambda c: disp_map.get(c, c))

    pool_idx = pool.set_index("canon")

    def _map_from_pool(column: str, default=None):
        if column not in pool_idx.columns:
            return pd.Series([default] * len(roster), index=roster.index)
        series = roster["PlayerName"].map(pool_idx[column])
        if default is not None:
            return series.fillna(default)
        return series

    roster["NoShowOverall"] = _map_from_pool("noshow_rate", 0.0).astype(float)
    roster["NoShowRolling"] = _map_from_pool("w_noshow_rate")
    roster["NoShowRolling"] = roster["NoShowRolling"].where(
        pd.notna(roster["NoShowRolling"]), roster["NoShowOverall"]
    ).fillna(0.0)
    roster["events_seen"] = _map_from_pool("events_seen", 0).astype(int)
    roster["noshow_count"] = _map_from_pool("noshow_count", 0).astype(int)
    roster["risk_penalty"] = _map_from_pool("risk_penalty", 0.0).astype(float)
    roster["AttendProb"] = _map_from_pool("attend_prob", 0.0).astype(float)
    roster["eb_p_hat"] = _map_from_pool("eb_p_hat")
    roster["eb_sigma"] = _map_from_pool("eb_sigma")
    roster["last_event"] = pd.to_datetime(
        _map_from_pool("last_event"), utc=True, errors="coerce"
    )
    roster["LastSeenDate"] = (
        roster["last_event"]
        .dt.tz_convert(TZ)
        .dt.strftime("%Y-%m-%d")
        .fillna("")
    )
    roster["last_noshow_event"] = pd.to_datetime(
        _map_from_pool("last_noshow_event"), utc=True, errors="coerce"
    )
    roster["LastNoShowDate"] = (
        roster["last_noshow_event"]
        .dt.tz_convert(TZ)
        .dt.strftime("%Y-%m-%d")
        .fillna("")
    )

    out_df = roster[
        [
            "DisplayName",
            "PlayerName",
            "Group",
            "Role",
            "NoShowOverall",
            "NoShowRolling",
            "AttendProb",
            "LastSeenDate",
            "LastNoShowDate",
            "events_seen",
            "noshow_count",
            "risk_penalty",
            "eb_p_hat",
            "eb_sigma",
        ]
    ].copy()
    out_df = out_df.rename(columns={"DisplayName": "PlayerName", "PlayerName": "Canonical"})

    if "_selection_stage" in roster.columns:
        out_df["SelectionStage"] = roster["_selection_stage"]

    out_df["events_seen"] = out_df["events_seen"].fillna(0).astype(int)
    out_df["noshow_count"] = out_df["noshow_count"].fillna(0).astype(int)
    out_df["risk_penalty"] = pd.to_numeric(out_df["risk_penalty"], errors="coerce").fillna(0.0)
    out_df["AttendProb"] = pd.to_numeric(out_df["AttendProb"], errors="coerce").fillna(0.0)

    role_order = {"Start": 0, "Ersatz": 1}
    group_order = {"A": 0, "B": 1}
    out_df["_ord"] = out_df["Group"].map(group_order) * 10 + out_df["Role"].map(role_order)
    out_df = out_df.sort_values(["_ord", "PlayerName"]).drop(columns=["_ord"]).reset_index(drop=True)

    actual_counts = {g: {r: 0 for r in ["Start", "Ersatz"]} for g in GROUPS}
    expected_attendance = {g: {"starters": 0.0, "subs": 0.0, "total": 0.0} for g in GROUPS}
    for g in GROUPS:
        for r in ["Start", "Ersatz"]:
            mask = (roster["Group"] == g) & (roster["Role"] == r)
            actual_counts[g][r] = int(mask.sum())
            expected_attendance[g]["starters" if r == "Start" else "subs"] = float(roster.loc[mask, "AttendProb"].sum())
        expected_attendance[g]["total"] = expected_attendance[g]["starters"] + expected_attendance[g]["subs"]

    missing_slots = {
        g: {
            r: max(target_caps_by_group_role.get(g, {}).get(r, 0) - actual_counts[g][r], 0)
            for r in ["Start", "Ersatz"]
        }
        for g in GROUPS
    }

    # Per-Team-Soll-Anwesenheit: basiert auf verfügbaren Slots (Starter + Ersatz)
    # und einer globalen Zielquote. Der Wert wird auf ganze Spieler gerundet und
    # nie größer als die maximale Slot-Anzahl pro Team gesetzt. Die alten
    # globalen Zielkorridore werden weiterhin für die Bandbreite genutzt, aber
    # nicht mehr direkt einem Team zugeschlagen.
    attendance_target_fraction = min(
        max(float(getattr(attendance_config, "attendance_target_fraction", 0.8)), 0.0),
        1.0,
    )
    slot_caps_by_team = {}
    attendance_target_by_team: Dict[str, int] = {}
    attendance_diff_by_team: Dict[str, float] = {}
    for g in GROUPS:
        starters_cap = int(target_caps_by_group_role.get(g, {}).get("Start", STARTERS_PER_GROUP))
        bench_cap = int(target_caps_by_group_role.get(g, {}).get("Ersatz", SUBS_PER_GROUP))
        max_slots = max(0, starters_cap + bench_cap)
        slot_caps_by_team[g] = {
            "starters_total": starters_cap,
            "bench_total": bench_cap,
            "max_slots": max_slots,
        }
        target_raw = round(max_slots * attendance_target_fraction)
        attendance_target_by_team[g] = int(min(target_raw, max_slots))
        attendance_diff_by_team[g] = expected_attendance[g]["total"] - attendance_target_by_team[g]

    def _by(grp: str, role: str) -> List[str]:
        return out_df[(out_df["Group"] == grp) & (out_df["Role"] == role)]["PlayerName"].tolist()

    def _stage_counts(grp: str, role: str) -> Dict[str, int]:
        if "_selection_stage" not in roster.columns:
            return {}
        mask = (roster["Group"] == grp) & (roster["Role"] == role)
        return roster.loc[mask, "_selection_stage"].value_counts().to_dict()

    def _float_default(val, default=0.0):
        if pd.isna(val):
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def _float_or_none(val):
        if pd.isna(val):
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _suggested_role_for_team(team: str) -> str:
        missing_start = missing_slots.get(team, {}).get("Start", 0)
        missing_sub = missing_slots.get(team, {}).get("Ersatz", 0)
        if missing_start > 0:
            return "Start"
        if missing_sub > 0:
            return "Ersatz"
        return "Ersatz"

    def _risk_category(attend_prob: float, events_seen: int) -> str:
        if events_seen <= callup_config.low_n_max_events:
            return "low_n"
        if attend_prob >= 0.8:
            return "low"
        if attend_prob >= 0.6:
            return "medium"
        return "high"

    def _int_default(val, default=0):
        if pd.isna(val):
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def _pct_label(val: Optional[float]) -> str:
        if val is None:
            return "–"
        try:
            return f"{float(val):.1%}"
        except (TypeError, ValueError):
            return "–"

    def _detect_callup_recommendation(
        noshow_overall: Optional[float],
        noshow_rolling: Optional[float],
        events_seen: Optional[int],
    ) -> Dict[str, object]:
        reasons = []
        ev = events_seen if events_seen is not None else None
        overall = noshow_overall if noshow_overall is not None else None
        rolling = noshow_rolling if noshow_rolling is not None else None

        if ev is not None and ev <= callup_config.low_n_max_events:
            reasons.append(
                {
                    "code": "low_n",
                    "label": f"Low-N ({ev} Event{'s' if ev != 1 else ''})",
                }
            )

        meets_event_min = ev is not None and ev >= callup_config.min_events

        if meets_event_min and overall is not None and overall >= callup_config.high_overall_threshold:
            reasons.append(
                {
                    "code": "high_overall",
                    "label": f"High No-Show overall {_pct_label(overall)}",
                }
            )

        if meets_event_min and rolling is not None and rolling >= callup_config.high_rolling_threshold:
            reasons.append(
                {
                    "code": "high_rolling",
                    "label": f"High No-Show rolling {_pct_label(rolling)}",
                }
            )

        if (
            meets_event_min
            and rolling is not None
            and overall is not None
            and rolling >= callup_config.rolling_uptick_min
            and rolling >= overall + callup_config.rolling_uptick_delta
        ):
            reasons.append(
                {
                    "code": "rolling_uptick",
                    "label": (
                        "Rolling-Uptick: "
                        f"rolling {_pct_label(rolling)} vs. overall {_pct_label(overall)}"
                    ),
                }
            )

        return {"recommended": bool(reasons), "reasons": reasons}

    schema_block = {
        "version": 4,
        "csv": [
            "PlayerName",
            "Canonical",
            "Group",
            "Role",
            "NoShowOverall",
            "NoShowRolling",
            "LastSeenDate",
            "risk_penalty",
        ],
        "groups": GROUPS,
        "roles": ["Start", "Ersatz"],
        "capacities": {"Start": STARTERS_PER_GROUP, "Ersatz": SUBS_PER_GROUP},
        "eb": {
            "enabled": bool(cfg.EB_ENABLE),
            "n0": float(cfg.EB_N0),
            "lambda": float(cfg.EB_LAMBDA),
            "winsorize": bool(cfg.WINSORIZE),
        },
        "prior": {
            "fallback": float(cfg.PRIOR_FALLBACK),
            "pad": float(cfg.PRIOR_PAD),
            "team_mean": float(p0),
            "value": float(prior_with_pad),
        },
        "metrics": {
            "risk_penalty": {
                "description": "Penalty summarizing expected no-show risk (0 = best, higher = worse)",
                "range": [0.0, 1.0],
            }
        },
    }

    forced_by_canon = {f["canon"]: f for f in forced_signups}

    players_payload = []
    callup_recommended_total = 0
    callup_reason_counts: Dict[str, int] = {}
    for row in out_df.itertuples(index=False):
        entry = {
            "display": row.PlayerName,
            "canon": row.Canonical,
            "group": row.Group,
            "role": row.Role,
            "noshow_overall": _float_default(row.NoShowOverall, 0.0),
            "noshow_rolling": _float_default(row.NoShowRolling, 0.0),
            "attend_prob": _float_default(row.AttendProb, 0.0),
            "last_seen": row.LastSeenDate,
            "last_noshow_date": row.LastNoShowDate or None,
            "events_seen": _int_default(row.events_seen, 0),
            "noshow_count": _int_default(row.noshow_count, 0),
            "risk_penalty": _float_default(row.risk_penalty, 0.0),
        }
        entry["selection_stage"] = getattr(row, "SelectionStage", None)
        entry["is_absent_next_event"] = bool(row.Canonical in absent_now)
        callup_info = _detect_callup_recommendation(
            noshow_overall=_float_or_none(row.NoShowOverall),
            noshow_rolling=_float_or_none(row.NoShowRolling),
            events_seen=_int_default(row.events_seen, None),
        )
        entry["callup"] = callup_info
        entry["callup_recommended"] = bool(callup_info.get("recommended"))

        callup_reason_codes: List[str] = []
        for reason in callup_info.get("reasons", []):
            if not isinstance(reason, dict):
                continue
            code = str(reason.get("code") or "unknown")
            callup_reason_codes.append(code)

        entry["callup_reason_codes"] = callup_reason_codes
        entry["callup_reason"] = callup_reason_codes[0] if callup_reason_codes else None

        if entry["callup_recommended"]:
            callup_recommended_total += 1
            for code in callup_reason_codes:
                callup_reason_counts[code] = callup_reason_counts.get(code, 0) + 1
        if row.Canonical in forced_by_canon:
            entry["forced_signup"] = {
                "commitment": forced_by_canon[row.Canonical].get("commitment", "hard"),
                "source": forced_by_canon[row.Canonical].get("source"),
                "note": forced_by_canon[row.Canonical].get("note"),
                "overbooked": bool(forced_by_canon[row.Canonical].get("overbooked")),
            }
            entry["has_forced_signup"] = True
        resp_meta = response_by_canon.get(str(row.Canonical))
        if resp_meta:
            entry["event_response"] = {
                "status": resp_meta.get("status"),
                "source": resp_meta.get("source"),
                "note": resp_meta.get("note", ""),
            }
            entry["has_event_response"] = True
        entry["next_event_status"] = next_event_status.get(str(row.Canonical), "open")
        if cfg.EB_ENABLE:
            entry["eb"] = {
                "p0": float(p0),
                "n0": float(cfg.EB_N0),
                "p_hat": _float_or_none(row.eb_p_hat),
                "sigma": _float_or_none(row.eb_sigma),
            }
        players_payload.append(entry)

    alliance_payload = []
    for row in alliance_df.itertuples(index=False):
        pref_group_val = getattr(row, "PrefGroup", pd.NA)
        if pd.isna(pref_group_val):
            pref_group_val = None
        else:
            pref_group_val = str(pref_group_val)
        alliance_payload.append(
            {
                "display": row.DisplayName,
                "canon": row.canon,
                "in_alliance": int(getattr(row, "InAlliance", 0)),
                "pref_group": pref_group_val,
            }
        )

    players_by_canon = {p["canon"]: p for p in players_payload}

    if absent_now:
        for canon in sorted(absent_now):
            if canon in players_by_canon:
                players_by_canon[canon]["is_absent_next_event"] = True
                continue
            meta = active_abs_meta.get(canon, {}) if active_abs_meta else {}
            players_payload.append(
                {
                    "display": disp_map.get(canon, canon),
                    "canon": canon,
                    "group": None,
                    "role": None,
                    "is_absent_next_event": True,
                    "absence_reason": meta.get("reason", ""),
                    "absence_scope": meta.get("scope", ""),
                    "absence_from": meta.get("from", ""),
                    "absence_to": meta.get("to", ""),
                    "next_event_status": next_event_status.get(str(canon), "absent"),
                }
            )
        players_by_canon = {p["canon"]: p for p in players_payload}

    if absent_now and not event_signups_df.empty:
        hard_conflicts = event_signups_df[
            (event_signups_df["Commitment"] == "hard") & (event_signups_df["canon"].isin(absent_now))
        ]
        for row in hard_conflicts.itertuples(index=False):
            canon_val = getattr(row, "canon", pd.NA)
            display = players_by_canon.get(canon_val, {}).get("display") if canon_val in players_by_canon else None
            absence_conflicts.append(
                {
                    "canonical": canon_val,
                    "display": display or getattr(row, "PlayerName", "") or canon_val,
                    "has_hard_commitment": True,
                    "is_absent": True,
                    "note": "hard commitment + absence_next_event",
                }
            )

    if decline_canons and not event_signups_df.empty:
        decline_conflicts = event_signups_df[
            (event_signups_df["Commitment"] == "hard") & (event_signups_df["canon"].isin(decline_canons))
        ]
        for row in decline_conflicts.itertuples(index=False):
            canon_val = getattr(row, "canon", pd.NA)
            meta = response_by_canon.get(str(canon_val), {})
            display = players_by_canon.get(canon_val, {}).get("display") if canon_val in players_by_canon else None
            event_response_conflicts.append(
                {
                    "canonical": canon_val,
                    "display": display or getattr(row, "PlayerName", "") or canon_val,
                    "has_hard_commitment": True,
                    "status": meta.get("status", "decline"),
                    "note": "hard commitment + event_response_decline",
                }
            )

    # --------------------------
    # Event-Zusagen als Overlay + harte Zusagen
    # --------------------------
    # Konzept: Der Pool in data/event_signups_next.csv gehört immer zum nächsten
    # Event (= aktuelle Aufstellung). Es gibt daher keine EventID-Spalte.
    # Spieler, die bereits im Optimizer-Roster stehen, werden markiert
    # (event_signup). Alle übrigen Zusagen landen pro Gruppe in "extra_signups".
    #
    # Neu: Commitment="hard" aus dem Pool führt dazu, dass die Spieler bereits
    # vor dem Optimizer gesetzt werden (siehe forced_signups oben). Overlay
    # bleibt für alle anderen Signups erhalten.
    extra_signups_by_group = {g: [] for g in GROUPS}
    file_rows_total = int(event_signup_load_meta.get("raw_rows", len(event_signups_df)))
    file_rows_with_name = int(
        event_signup_load_meta.get("rows_with_playername", len(event_signups_df))
    )
    file_rows_with_canon = int(
        event_signup_load_meta.get("rows_with_canon", len(event_signups_df))
    )
    signups_meta = {
        "scope": "next_event",
        "source": str(Path(args.event_signups)),
        "raw_rows": file_rows_total,
        "rows_with_playername": file_rows_with_name,
        "rows_with_canon": file_rows_with_canon,
        "file_rows_total": file_rows_total,
        "file_rows_with_playername": file_rows_with_name,
        "file_rows_with_canon": file_rows_with_canon,
        "total_entries": int(len(event_signups_df)),
        "applied_entries": 0,
        "ignored_entries": 0,
        "hard_commitments": hard_signup_total,
        "hard_commit_rows_total": int(
            event_signup_load_meta.get("hard_commitments", hard_signup_total)
        ),
        "hard_signups_only": hard_signups_only,
        "hard_commitments_total": int(len(hard_signup_canons)),
        "builder_candidates_total": int(builder_pool_stats.get("builder_candidates_total", len(builder_pool))),
        "builder_filtered_out": int(builder_pool_stats.get("filtered_out", 0)),
    }

    if absences_payload.get("players"):
        absences_payload["conflicting_forced_signups"] = [
            item for item in invalid_forced_signups if item.get("reason") == "absent"
        ]

    if not event_signups_df.empty:
        seen_extra = set()
        for row in event_signups_df.itertuples(index=False):
            display = getattr(row, "PlayerName", "") or ""
            canon = getattr(row, "canon", pd.NA)
            group = (getattr(row, "Group", "") or "").strip().upper()
            role = (getattr(row, "Role", "") or "").strip().title()
            source = (getattr(row, "Source", "") or "manual").strip()
            note = (getattr(row, "Note", "") or "").strip()

            if canon in players_by_canon:
                base = players_by_canon[canon]
                base["event_signup"] = {
                    "group": group or base.get("group"),
                    "role": role or base.get("role"),
                    "source": source,
                    "note": note,
                }
                base["has_event_signup"] = True
                signups_meta["applied_entries"] += 1
                continue

            if group not in GROUPS:
                signups_meta["ignored_entries"] += 1
                continue

            key = (canon, group, role or "", note or "", source)
            if key in seen_extra:
                continue
            seen_extra.add(key)
            extra_signups_by_group[group].append(
                {
                    "player": display,
                    "canon": canon,
                    "group": group,
                    "role": role or None,
                    "source": source,
                    "note": note,
                }
            )
            signups_meta["applied_entries"] += 1

    forced_signup_total = len(forced_signups)
    signups_meta["hard_commitments_applied"] = forced_signup_total
    signups_meta["hard_commitments_invalid"] = len(invalid_forced_signups)
    signups_meta["hard_commitments_overbooked"] = len(overbooked_forced_signups)
    signups_meta["extra_entries_total"] = int(sum(len(v) for v in extra_signups_by_group.values()))
    signups_meta["extra_entries_by_group"] = {g: len(extra_signups_by_group.get(g, [])) for g in GROUPS}

    hard_missing_from_roster = max(
        0,
        hard_signup_total
        - signups_meta["hard_commitments_applied"]
        - signups_meta["hard_commitments_invalid"],
    )
    forced_in_roster = sum(1 for p in players_payload if p.get("has_forced_signup"))
    forced_out_of_roster = max(0, forced_signup_total - forced_in_roster)
    signups_meta["forced_total"] = forced_signup_total
    signups_meta["forced_in_roster"] = forced_in_roster
    signups_meta["forced_out_of_roster"] = forced_out_of_roster
    file_rows_total = signups_meta.get("file_rows_total", signups_meta["raw_rows"])
    processed_entries_total = signups_meta["total_entries"]
    hard_rows_total = signups_meta.get("hard_commit_rows_total", hard_signup_total)
    signup_pool_stats = {
        "file_rows_total": file_rows_total,
        "file_entries_total": file_rows_total,
        "raw_rows": signups_meta["raw_rows"],
        "rows_with_playername": signups_meta["rows_with_playername"],
        "rows_with_canon": signups_meta["rows_with_canon"],
        "file_rows_with_playername": signups_meta.get("file_rows_with_playername", signups_meta["rows_with_playername"]),
        "file_rows_with_canon": signups_meta.get("file_rows_with_canon", signups_meta["rows_with_canon"]),
        "total_entries": processed_entries_total,
        "processed_entries_total": processed_entries_total,
        "applied_entries": signups_meta["applied_entries"],
        "ignored_entries": signups_meta["ignored_entries"],
        "hard_commit_rows_total": hard_rows_total,
        "hard_commit_total": hard_rows_total,
        "hard_commit_applied": signups_meta["hard_commitments_applied"],
        "hard_commit_invalid": signups_meta["hard_commitments_invalid"],
        "hard_commit_overbooked": signups_meta["hard_commitments_overbooked"],
        "hard_commit_missing_from_roster": hard_missing_from_roster,
        "hard_commitments_total": hard_rows_total,
        "hard_commitments_applied": signups_meta["hard_commitments_applied"],
        "hard_commitments_invalid": signups_meta["hard_commitments_invalid"],
        "hard_commitments_overbooked": signups_meta["hard_commitments_overbooked"],
        "hard_commitments_missing_from_roster": hard_missing_from_roster,
        "in_roster_hard_commitments": forced_in_roster,
        "forced_total": forced_signup_total,
        "forced_in_roster": forced_in_roster,
        "forced_out_of_roster": forced_out_of_roster,
        "extra_entries_total": signups_meta["extra_entries_total"],
        "extra_entries_by_group": signups_meta["extra_entries_by_group"],
        "hard_signups_only": hard_signups_only,
        "builder_candidates_total": int(builder_pool_stats.get("builder_candidates_total", len(builder_pool))),
        "builder_filtered_out": int(builder_pool_stats.get("filtered_out", 0)),
    }
    signup_pool_payload = {
        "source": signups_meta["source"],
        "stats": signup_pool_stats,
        "file_entries": signup_file_entries,
        "forced_signups": forced_signups,
        "invalid_forced_signups": invalid_forced_signups,
        "overbooked_forced_signups": overbooked_forced_signups,
    }
    signup_pool_payload.update(signup_pool_stats)

    callup_config_snapshot = callup_config.to_snapshot()
    callup_rules_legacy = {
        "min_events": callup_config.min_events,
        "low_n_max_events": callup_config.low_n_max_events,
        "overall_high": callup_config.high_overall_threshold,
        "rolling_high": callup_config.high_rolling_threshold,
        "rolling_uptick_delta": callup_config.rolling_uptick_delta,
        "rolling_uptick_min": callup_config.rolling_uptick_min,
    }

    callup_stats = {
        "schema": 2,
        "recommended_total": int(callup_recommended_total),
        "reasons": callup_reason_counts,
        "rules": callup_rules_legacy,
        "config_snapshot": callup_config_snapshot,
        "config_source": callup_config_meta,
    }

    attendance_targets = attendance_config.target_expected()
    attendance_target_status = {}
    for g in GROUPS:
        bounds = attendance_targets.get(g, {}) or {}
        expected_total = expected_attendance.get(g, {}).get("total", 0.0)
        if not bounds:
            attendance_target_status[g] = "unknown"
            continue
        if expected_total < bounds.get("low", expected_total):
            attendance_target_status[g] = "below_target"
        elif expected_total > bounds.get("high", expected_total):
            attendance_target_status[g] = "above_target"
        else:
            attendance_target_status[g] = "within_target"

    reliable_pool = int((pool["attend_prob"] >= callup_min_attend_prob).sum())
    team_overview: Dict[str, Dict[str, object]] = {}
    summary_lines: List[str] = []
    for g in GROUPS:
        starters_mask = (roster["Group"] == g) & (roster["Role"] == "Start")
        bench_mask = (roster["Group"] == g) & (roster["Role"] == "Ersatz")
        starters_total = int(starters_mask.sum())
        bench_total = int(bench_mask.sum())
        starters_at_threshold = int(
            (roster.loc[starters_mask, "AttendProb"] >= callup_min_attend_prob).sum()
        )
        bench_at_threshold = int(
            (roster.loc[bench_mask, "AttendProb"] >= callup_min_attend_prob).sum()
        )
        starters_below = max(starters_total - starters_at_threshold, 0)
        bench_below = max(bench_total - bench_at_threshold, 0)
        missing = missing_slots.get(g, {"Start": 0, "Ersatz": 0}) or {"Start": 0, "Ersatz": 0}
        expected_meta = expected_attendance.get(g, {}) or {}
        start_stage_counts = _stage_counts(g, "Start")
        bench_stage_counts = _stage_counts(g, "Ersatz")
        fallback_starters = int(start_stage_counts.get(f"{g}-start-fallback", 0)) if g == "B" else 0
        forced_starters = int(start_stage_counts.get("forced", 0))
        forced_bench = int(bench_stage_counts.get("forced", 0))

        risk_reasons: List[str] = []
        risk_level = "low"
        if missing.get("Start", 0) > 0:
            risk_reasons.append(
                f"{missing.get('Start', 0)} Starter-Slots bewusst frei – keine weiteren Spieler ≥ {callup_min_attend_prob:.0%}"
            )
            risk_level = "high"
        if g == "B" and fallback_starters > 0:
            risk_reasons.append(
                f"{fallback_starters} Starter für Team B aus Fallback < Schwelle"
            )
            risk_level = "moderate" if risk_level == "low" else risk_level
        if starters_below > 0:
            risk_reasons.append(
                f"{starters_below} Starter unter Schwelle {callup_min_attend_prob:.0%} (Team A wird immer aufgefüllt)"
            )
            risk_level = "moderate" if risk_level == "low" else risk_level

        parts = [
            f"Starter: {starters_total} (≥ Schwelle: {starters_at_threshold}, unter Schwelle: {starters_below})",
            f"Erwartete Anwesenheit Starter: {expected_meta.get('starters', 0.0):.1f}",
        ]
        if fallback_starters > 0:
            parts.append(f"Fallback-Starter (< Schwelle): {fallback_starters}")
        if bench_total > 0:
            parts.append(
                f"Ersatz: {bench_total} (≥ Schwelle: {bench_at_threshold}, unter Schwelle: {bench_below})"
            )
        if missing.get("Ersatz", 0) > 0:
            parts.append(f"Ersatz-Slots frei: {missing.get('Ersatz', 0)}")
        if risk_reasons:
            parts.append("Risiken: " + "; ".join(risk_reasons))

        risk_text = "; ".join(risk_reasons) if risk_reasons else "Risiko gering"
        team_overview[g] = {
            "starters": {
                "total": starters_total,
                "at_threshold": starters_at_threshold,
                "below_threshold": starters_below,
                "fallback": fallback_starters,
                "forced": forced_starters,
            },
            "bench": {
                "total": bench_total,
                "at_threshold": bench_at_threshold,
                "below_threshold": bench_below,
                "forced": forced_bench,
            },
            "missing_slots": missing,
            "expected_attendance": expected_meta,
            "attendance_target": attendance_target_by_team.get(g),
            "attendance_diff": attendance_diff_by_team.get(g),
            "slots": slot_caps_by_team.get(g, {}),
            "risk_level": risk_level,
            "risk_text": risk_text,
            "summary": "; ".join(parts),
            "stage_counts": {"start": start_stage_counts, "bench": bench_stage_counts},
        }
        summary_lines.append(
            (
                f"Team {g}: {starters_total} Starter"
                + (f", Fallback {fallback_starters}" if fallback_starters and g == "B" else "")
                + f", erwartete Anwesenheit {expected_meta.get('starters', 0.0):.1f}"
            )
        )

    attendance_summary = {
        "schema": 2,
        "expected_by_team": expected_attendance,
        "missing_slots": missing_slots,
        "pool_total_expected": float(pool["attend_prob"].sum()),
        "targets": attendance_targets,
        "targets_by_team": attendance_target_by_team,
        "target_fraction": attendance_target_fraction,
        "target_diff": attendance_diff_by_team,
        "slots_by_team": slot_caps_by_team,
        "target_status": attendance_target_status,
        "config_snapshot": attendance_config.to_snapshot(),
        "config_source": attendance_config_meta,
        "threshold": callup_min_attend_prob,
        "reliable_pool": reliable_pool,
        "teams": team_overview,
        "recommendation": {
            "text": " | ".join(summary_lines),
        },
    }

    roster_canons = set(roster["PlayerName"].dropna().astype(str).tolist())
    nominal_prob_by_team = {"A": float(attendance_config.min_bench_A), "B": float(attendance_config.min_bench_B)}

    callup_candidate_df = pool[~pool["canon"].isin(roster_canons)].copy()
    if seen_forced:
        callup_candidate_df = callup_candidate_df[~callup_candidate_df["canon"].isin(seen_forced)]
    if decline_canons:
        callup_candidate_df = callup_candidate_df[~callup_candidate_df["canon"].isin(decline_canons)]
    if noresp_canons:
        callup_candidate_df = callup_candidate_df[~callup_candidate_df["canon"].isin(noresp_canons)]

    callup_candidate_df["attend_prob"] = pd.to_numeric(
        callup_candidate_df["attend_prob"], errors="coerce"
    ).fillna(0.0)
    callup_candidate_df["events_seen"] = pd.to_numeric(
        callup_candidate_df["events_seen"], errors="coerce"
    ).fillna(0)

    callup_candidate_df = callup_candidate_df[
        callup_candidate_df["attend_prob"] >= callup_min_attend_prob
    ].copy()

    callup_needs: Dict[str, Dict[str, object]] = {}
    for g in GROUPS:
        target_caps = target_caps_by_group_role.get(g, {})
        expected_gap = max(
            attendance_target_by_team.get(g, 0) - expected_attendance[g]["total"],
            0.0,
        )
        nominal_prob = max(nominal_prob_by_team.get(g, 0.5), 0.01)
        expected_gap_players = int(math.ceil(expected_gap / nominal_prob)) if expected_gap else 0
        missing_total = missing_slots.get(g, {}).get("Start", 0) + missing_slots.get(g, {}).get("Ersatz", 0)
        suggested = max(missing_total, expected_gap_players)
        callup_needs[g] = {
            "missing": missing_slots.get(g, {}),
            "target_slots": target_caps,
            "planned_slots": actual_counts.get(g, {}),
            "expected_attendance": expected_attendance.get(g, {}),
            "expected_gap": expected_gap,
            "expected_gap_players": expected_gap_players,
            "suggested_callups": suggested,
        }

    def _build_callup_entry(row, team: str) -> Dict[str, object]:
        display = getattr(row, "DisplayName", "") or getattr(row, "PlayerName", "") or getattr(row, "canon", "")
        canon_val = getattr(row, "canon", "")
        attend_prob_val = float(getattr(row, "attend_prob", 0.0) or 0.0)
        events_seen_val = int(getattr(row, "events_seen", 0) or 0)
        role_hint = _suggested_role_for_team(team)
        pref_group_raw = getattr(row, "PrefGroup", pd.NA)
        pref_group = None if pd.isna(pref_group_raw) else str(pref_group_raw).strip().upper()
        risk = _risk_category(attend_prob_val, events_seen_val)
        status = next_event_status.get(str(canon_val), "open")
        reason_parts = [f"AttendProb {attend_prob_val:.0%}"]
        if pref_group:
            reason_parts.append(f"Präferenz {pref_group}")
        if risk == "low_n":
            reason_parts.append("wenig Historie")
        if status not in {"open", "signup"}:
            reason_parts.append(f"Status: {status}")
        reason_text = "; ".join(reason_parts)
        return {
            "display": display,
            "canon": canon_val,
            "attend_prob": attend_prob_val,
            "events_seen": events_seen_val,
            "risk": risk,
            "recommended_team": team,
            "recommended_role": role_hint,
            "pref_group": pref_group,
            "next_event_status": status,
            "reason": reason_text,
        }

    callup_suggestions: Dict[str, object] = {
        "schema": 1,
        "meta": {
            "min_attend_prob": callup_min_attend_prob,
            "candidates": int(len(callup_candidate_df)),
            "note": "Nur Spieler außerhalb des Rosters, ohne Absagen/No-Response/Hard-Commitment",
        },
        "needs": callup_needs,
        "teams": {},
    }

    sorted_candidates = callup_candidate_df.sort_values(
        by=["attend_prob", "risk_penalty", "DisplayName"], ascending=[False, True, True]
    )

    for g in GROUPS:
        target_count = max(callup_needs.get(g, {}).get("suggested_callups", 0), 0)
        target_count = max(target_count, 6) if g == "B" else target_count
        ranked: List[Dict[str, object]] = []
        for row in sorted_candidates.itertuples(index=False):
            entry = _build_callup_entry(row, g)
            ranked.append(entry)
            if target_count and len(ranked) >= int(target_count * 2):
                break
        callup_suggestions["teams"][g] = {
            "suggestions": ranked,
            "target_count": int(target_count),
        }

    roster_status_by_canon = {}
    for row in out_df.itertuples(index=False):
        canon_key = str(getattr(row, "Canonical", ""))
        group_val = getattr(row, "Group", "") or ""
        role_val = getattr(row, "Role", "") or ""
        roster_status_by_canon[canon_key] = f"{group_val}-{role_val}" if group_val and role_val else "-"

    hist_idx = hist.set_index("canon") if "canon" in hist.columns else pd.DataFrame()
    pool_metrics_idx = pool.set_index("canon") if "canon" in pool.columns else pd.DataFrame()

    def _overview_metrics(canon: str) -> Dict[str, object]:
        if canon in pool_metrics_idx.index:
            row = pool_metrics_idx.loc[canon]
            noshow_overall = _float_default(getattr(row, "noshow_rate", 0.0), 0.0)
            noshow_rolling = _float_default(getattr(row, "w_noshow_rate", noshow_overall), noshow_overall)
            attend_prob_val = _float_default(getattr(row, "attend_prob", None), None)
            events_seen_val = _int_default(getattr(row, "events_seen", None), 0)
            return {
                "noshow_overall": noshow_overall,
                "noshow_rolling": noshow_rolling,
                "attend_prob": attend_prob_val,
                "events_seen": events_seen_val,
                "noshow_count": _int_default(getattr(row, "noshows_total", getattr(row, "noshow_count", None)), 0),
            }

        if canon in hist_idx.index:
            row = hist_idx.loc[canon]
            events_seen_val = _int_default(getattr(row, "assignments_total", None), 0)
            noshow_overall = _float_default(getattr(row, "noshow_rate", 0.0), 0.0)
            noshow_rolling = _float_default(getattr(row, "w_noshow_rate", noshow_overall), noshow_overall)
            base_prob = (1.0 - noshow_rolling) if events_seen_val > 0 else 1.0 - prior_with_pad
            attend_prob_val = max(min(base_prob, 1.0), 0.0)
            return {
                "noshow_overall": noshow_overall,
                "noshow_rolling": noshow_rolling,
                "attend_prob": attend_prob_val,
                "events_seen": events_seen_val,
                "noshow_count": _int_default(getattr(row, "noshows_total", None), 0),
            }

        return {
            "noshow_overall": None,
            "noshow_rolling": None,
            "attend_prob": None,
            "events_seen": 0,
            "noshow_count": 0,
        }

    def _contact_recommendation(entry: Dict[str, object]) -> str:
        if not bool(entry.get("in_alliance", False)):
            return "former"
        if entry.get("event_status") == "decline" or entry.get("is_absent_next_event"):
            return "no"
        attend_prob_val = entry.get("attend_prob")
        if isinstance(attend_prob_val, (int, float)) and not pd.isna(attend_prob_val):
            if attend_prob_val >= float(callup_config.callup_min_attend_prob):
                return "yes"
        return "maybe"

    overview_players: List[Dict[str, object]] = []
    for row in alliance_df.itertuples(index=False):
        canon_key = getattr(row, "canon", "") or ""
        display_val = getattr(row, "DisplayName", canon_key) or canon_key
        metrics = _overview_metrics(canon_key)
        events_seen_val = metrics.get("events_seen", 0) or 0
        no_data_flag = events_seen_val <= 0
        low_n_flag = 0 < events_seen_val <= callup_config.low_n_max_events
        event_status_val = next_event_status.get(str(canon_key), "open")
        is_absent_flag = bool(canon_key in absent_now)
        absence_meta = active_abs_meta.get(str(canon_key), {}) if active_abs_meta else {}

        entry = {
            "display": display_val,
            "canon": canon_key,
            "in_alliance": int(getattr(row, "InAlliance", 0)),
            "roster_status": roster_status_by_canon.get(canon_key, "-"),
            "event_status": event_status_val,
            "is_absent_next_event": is_absent_flag,
            "absence": {
                "reason": absence_meta.get("reason", ""),
                "scope": absence_meta.get("scope", ""),
                "from": absence_meta.get("from", ""),
                "to": absence_meta.get("to", ""),
            },
            "attend_prob": metrics.get("attend_prob"),
            "noshow_overall": metrics.get("noshow_overall"),
            "noshow_rolling": metrics.get("noshow_rolling"),
            "events_seen": events_seen_val,
            "noshow_count": metrics.get("noshow_count"),
            "flags": {
                "no_data": bool(no_data_flag),
                "low_n": bool(low_n_flag),
            },
        }
        entry["contact_recommendation"] = _contact_recommendation(entry)
        overview_players.append(entry)

    overview_players = sorted(overview_players, key=lambda e: (str(e.get("display") or "")))

    active_overview_count = sum(1 for entry in overview_players if entry.get("in_alliance"))
    former_overview_count = len(overview_players) - active_overview_count
    alliance_overview_payload = {
        "schema": 1,
        "meta": {
            "callup_min_attend_prob": float(callup_config.callup_min_attend_prob),
            "players": active_overview_count,
            "players_total": len(overview_players),
            "players_active": active_overview_count,
            "players_former": former_overview_count,
        },
        "players": overview_players,
    }

    json_payload = {
        "generated_at": datetime.now(TZ).isoformat(),
        "schema": schema_block,
        "signup_pool": signup_pool_payload,
        "groups": {
            "A": {
                "Start": _by("A", "Start"),
                "Ersatz": _by("A", "Ersatz"),
                "extra_signups": extra_signups_by_group.get("A", []),
            },
            "B": {
                "Start": _by("B", "Start"),
                "Ersatz": _by("B", "Ersatz"),
                "extra_signups": extra_signups_by_group.get("B", []),
            },
        },
        "event_signups": signups_meta,
        "forced_signups": forced_signups,
        "invalid_forced_signups": invalid_forced_signups,
        "overbooked_forced_signups": overbooked_forced_signups,
        "alliance_pool": alliance_payload,
        "players": players_payload,
        "callup_stats": callup_stats,
        "absences": absences_payload,
        "absence_debug": absence_debug,
        "absence_conflicts": absence_conflicts,
        "event_responses": event_responses_payload,
        "event_response_conflicts": event_response_conflicts,
        "attendance": attendance_summary,
        "callup_suggestions": callup_suggestions,
        "alliance_next_event_overview": alliance_overview_payload,
    }

    selection_debug = roster.attrs.get("selection_debug")
    if selection_debug:
        json_payload["debug_selection"] = selection_debug

    _write_outputs(out_dir, out_df, json_payload)


if __name__ == "__main__":
    main()
