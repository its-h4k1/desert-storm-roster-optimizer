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
from pathlib import Path
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

import pandas as pd

from src.config import get_config
from src.utils import (
    canonical_name,
    build_deterministic_roster,
    STARTERS_PER_GROUP,
    SUBS_PER_GROUP,
    GROUPS,
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

CALLUP_RULES = {
    # Mindestmenge an Events, ab der Rolling/Overall-Metriken ernst genommen werden
    "min_events": 3,
    # Low-N-Heuristik (<= low_n_max_events → vorsorgliche Callup-Empfehlung)
    "low_n_max_events": 2,
    # High overall: No-Show-Rate über die gesamte Historie ist hoch
    "overall_high": 0.40,
    # High rolling: No-Show-Rate der letzten Events (gewichtet) ist hoch
    "rolling_high": 0.50,
    # Rolling-Uptick: Rolling klar schlechter als Overall
    "rolling_uptick_delta": 0.10,
    # Rolling-Uptick nur bewerten, wenn Rolling mindestens dieses Niveau erreicht
    "rolling_uptick_min": 0.25,
}


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
    for col in ["From", "To"]:
        if col not in df.columns:
            df[col] = ""

    _ensure_in_alliance_column(df, context="absences.csv")
    df = df[df["InAlliance"] == 1].copy()
    df["canon"] = df["PlayerName"].map(canonical_name)

    def _parse_local(s: str) -> Optional[pd.Timestamp]:
        s = (s or "").strip()
        if not s:
            return None
        ts = pd.to_datetime(s, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.tz_localize(TZ) if ts.tzinfo is None else ts.tz_convert(TZ)

    df["From_ts"] = df["From"].map(_parse_local)
    df["To_ts"] = df["To"].map(_parse_local)
    return df[["canon", "From_ts", "To_ts", "Reason"]].copy()


def _load_event_signups(path: str, to_canon) -> tuple[pd.DataFrame, Dict[str, int]]:
    """Load the next-event signup pool (manual confirmations for the upcoming roster).

    Analyse & Konzept (Stand heute):
    - CSV-Spalten im Repo: PlayerName, Group, Role, Source, Note.
      → liefern nur Overlay/Badges, keine "Verbindlichkeit".
    - Erweiterung: neue Spalte ``Commitment`` (default ``none``) mit Werten
      ``none`` | ``hard``.
      * none  = reine Overlay-Zusage (Badge/extra_signups), beeinflusst den
        Builder nicht.
      * hard  = verbindliche Zusage: Spieler soll – sofern aktiv, in der
        Allianz und nicht abwesend – vorab in den Roster gesetzt werden.
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
        return pd.DataFrame(columns=cols), meta
    except Exception as e:
        print(f"[warn] event signups: {path} nicht lesbar ({e}), starte leer")
        return pd.DataFrame(columns=cols), meta

    meta["raw_rows"] = int(len(df))

    for col in cols:
        if col not in df.columns:
            df[col] = ""

    df = df[cols].copy()
    df["PlayerName"] = df["PlayerName"].fillna("").astype(str).str.strip()
    df = df[df["PlayerName"] != ""]
    meta["rows_with_playername"] = int(len(df))
    df["canon"] = df["PlayerName"].map(to_canon)
    df = df[df["canon"].notna()].copy()
    meta["rows_with_canon"] = int(len(df))

    df["Group"] = df["Group"].fillna("").astype(str).str.strip().str.upper()
    df["Role"] = df["Role"].fillna("").astype(str).str.strip().str.title()
    df["Commitment"] = (
        df["Commitment"].fillna("none").astype(str).str.strip().str.lower().replace("", "none")
    )
    allowed_commitments = {"none", "hard"}
    df.loc[~df["Commitment"].isin(allowed_commitments), "Commitment"] = "none"
    meta["hard_commitments"] = int((df["Commitment"] == "hard").sum())
    df["Source"] = (
        df["Source"].fillna("manual_event_signup").astype(str).str.strip().replace("", "manual_event_signup")
    )
    df["Note"] = df["Note"].fillna("").astype(str)
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
    ap.add_argument("--absences", default="", help="Pfad zu data/absences.csv (optional)")
    ap.add_argument("--preferences", default="", help="Pfad zu data/preferences.csv (optional)")
    ap.add_argument(
        "--event-signups",
        default="data/event_signups_next.csv",
        help="Pfad zum Zusage-Pool für das nächste Event (ohne EventID-Spalte)",
    )
    ap.add_argument("--half-life-days", type=float, default=90.0, help="Halbwertszeit für Rolling-Metriken (Tage)")
    ap.add_argument("--out", default="out", help="Ausgabeverzeichnis für Run-Artefakte (zusätzlich zu out/latest.*)")
    args = ap.parse_args()

    cfg = get_config()
    out_dir = Path(args.out)

    # 1) Daten laden
    norm_patterns = _normalize_event_patterns(args.events)
    events_df = _load_events(norm_patterns)
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
    absent_now: set[str] = set()
    if args.absences:
        try:
            abs_df = _load_absences(args.absences)
            print(f"[ok] absences loaded: {len(abs_df)} Einträge")
        except Exception as e:
            print(f"[warn] absences nicht nutzbar: {e}")

    event_signups_df, event_signup_load_meta = _load_event_signups(args.event_signups, to_canon)
    print(
        "[info] event signups geladen: "
        f"{len(event_signups_df)} Einträge (Pool für nächstes Event) – "
        f"raw={event_signup_load_meta.get('raw_rows', 0)}, "
        f"with_name={event_signup_load_meta.get('rows_with_playername', 0)}, "
        f"canonical={event_signup_load_meta.get('rows_with_canon', 0)}, "
        f"hard={event_signup_load_meta.get('hard_commitments', 0)}"
    )

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

    # 4) Abwesenheiten (heute) filtern
    if abs_df is not None and not abs_df.empty:
        now_ts = _current_local_dt()
        def _in_range(row) -> bool:
            f, t = row["From_ts"], row["To_ts"]
            if f is not None and pd.notna(f) and now_ts < f:
                return False
            if t is not None and pd.notna(t) and now_ts > t:
                return False
            return True
        abs_df["is_absent_now"] = abs_df.apply(_in_range, axis=1)
        absent_now = set(abs_df.loc[abs_df["is_absent_now"], "canon"].tolist())
        before = len(pool)
        pool = pool[~pool["canon"].isin(absent_now)].copy()
        print(f"[info] absences filter: {before - len(pool)} ausgeschlossen (now={now_ts.isoformat()})")

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

    no_data_mask = pool["events_seen"] <= 0
    pool.loc[no_data_mask, "p_start"] = p0
    pool.loc[no_data_mask, "p_sub"] = p0
    pool["p_start"] = pool["p_start"].fillna(p0).clip(0.0, 1.0)
    pool["p_sub"] = pool["p_sub"].fillna(p0).clip(0.0, 1.0)

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
    pool_idx = pool.set_index("canon")
    in_alliance_set = set(alliance_df.loc[alliance_df["InAlliance"] == 1, "canon"])

    forced_signups: List[Dict] = []
    invalid_forced_signups: List[Dict] = []
    capacities_remaining = {g: {"Start": STARTERS_PER_GROUP, "Ersatz": SUBS_PER_GROUP} for g in GROUPS}

    hard_signups = event_signups_df[event_signups_df["Commitment"] == "hard"]
    seen_forced: set[str] = set()

    def _choose_group(canon: str, signup_group: str, pref_group: Optional[str]) -> str:
        desired = []
        if signup_group in GROUPS:
            desired.append(signup_group)
        if pref_group in GROUPS and pref_group not in desired:
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

    for row in hard_signups.itertuples(index=False):
        canon = getattr(row, "canon", pd.NA)
        display = getattr(row, "PlayerName", "") or ""
        group_pref = (getattr(row, "Group", "") or "").strip().upper()
        role_pref = (getattr(row, "Role", "") or "").strip().title()
        source = (getattr(row, "Source", "") or "manual_event_signup").strip()
        note = (getattr(row, "Note", "") or "").strip()

        if pd.isna(canon) or not str(canon).strip():
            invalid_forced_signups.append({"player": display, "reason": "unknown_player"})
            continue
        canon = str(canon)
        if canon in seen_forced:
            invalid_forced_signups.append({"player": display, "canon": canon, "reason": "duplicate"})
            continue
        if canon not in in_alliance_set:
            invalid_forced_signups.append({"player": display, "canon": canon, "reason": "not_in_alliance"})
            continue
        if canon in absent_now:
            invalid_forced_signups.append({"player": display, "canon": canon, "reason": "absent"})
            continue
        if canon not in pool_idx.index:
            invalid_forced_signups.append({"player": display, "canon": canon, "reason": "inactive_or_filtered"})
            continue

        pref_group_val = pool_idx.loc[canon].get("PrefGroup") if canon in pool_idx.index else pd.NA
        pref_group = None if pd.isna(pref_group_val) else str(pref_group_val).strip().upper()
        target_group = _choose_group(canon, group_pref, pref_group)
        target_role = _choose_role(target_group, role_pref)

        capacities_remaining[target_group][target_role] -= 1
        seen_forced.add(canon)
        forced_signups.append(
            {
                "player": display or canon,
                "canon": canon,
                "group": target_group,
                "role": target_role,
                "source": source,
                "note": note,
                "commitment": "hard",
                "overbooked": capacities_remaining[target_group][target_role] < 0,
            }
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

    # 6) Input für Builder (nur Rest-Slots)
    pool_for_builder = pool[~pool["canon"].isin(seen_forced)].copy()
    probs_for_builder = pd.DataFrame({
        "PlayerName": pool_for_builder["canon"],
        "p_start": pool_for_builder["p_start"].fillna(p0),
        "p_sub": pool_for_builder["p_sub"].fillna(p0),
        "PrefGroup": pool_for_builder.get("PrefGroup", pd.Series([pd.NA]*len(pool_for_builder))),
        "PrefMode": pool_for_builder.get("PrefMode", pd.Series([pd.NA]*len(pool_for_builder))),
        "PrefBoost": pool_for_builder.get("PrefBoost", pd.Series([pd.NA]*len(pool_for_builder))),
        "events_seen": pool_for_builder["events_seen"],
        "risk_penalty": pool_for_builder["risk_penalty"],
    })

    # 7) Roster bauen
    roster = build_deterministic_roster(
        probs_for_builder,
        forced_assignments=[
            {"PlayerName": f["canon"], "Group": f["group"], "Role": f["role"]}
            for f in forced_signups
        ],
        capacities_by_group_role=capacities_remaining,
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

    out_df["events_seen"] = out_df["events_seen"].fillna(0).astype(int)
    out_df["noshow_count"] = out_df["noshow_count"].fillna(0).astype(int)
    out_df["risk_penalty"] = pd.to_numeric(out_df["risk_penalty"], errors="coerce").fillna(0.0)

    role_order = {"Start": 0, "Ersatz": 1}
    group_order = {"A": 0, "B": 1}
    out_df["_ord"] = out_df["Group"].map(group_order) * 10 + out_df["Role"].map(role_order)
    out_df = out_df.sort_values(["_ord", "PlayerName"]).drop(columns=["_ord"]).reset_index(drop=True)

    def _by(grp: str, role: str) -> List[str]:
        return out_df[(out_df["Group"] == grp) & (out_df["Role"] == role)]["PlayerName"].tolist()

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

        if ev is not None and ev <= CALLUP_RULES["low_n_max_events"]:
            reasons.append(
                {
                    "code": "low_n",
                    "label": f"Low-N ({ev} Event{'s' if ev != 1 else ''})",
                }
            )

        meets_event_min = ev is not None and ev >= CALLUP_RULES["min_events"]

        if meets_event_min and overall is not None and overall >= CALLUP_RULES["overall_high"]:
            reasons.append(
                {
                    "code": "high_overall",
                    "label": f"High No-Show overall {_pct_label(overall)}",
                }
            )

        if meets_event_min and rolling is not None and rolling >= CALLUP_RULES["rolling_high"]:
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
            and rolling >= CALLUP_RULES["rolling_uptick_min"]
            and rolling >= overall + CALLUP_RULES["rolling_uptick_delta"]
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
            "last_seen": row.LastSeenDate,
            "last_noshow_date": row.LastNoShowDate or None,
            "events_seen": _int_default(row.events_seen, 0),
            "noshow_count": _int_default(row.noshow_count, 0),
            "risk_penalty": _float_default(row.risk_penalty, 0.0),
        }
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
    hard_signup_total = int((event_signups_df["Commitment"] == "hard").sum())
    signups_meta = {
        "scope": "next_event",
        "source": str(Path(args.event_signups)),
        "raw_rows": int(event_signup_load_meta.get("raw_rows", 0)),
        "rows_with_playername": int(event_signup_load_meta.get("rows_with_playername", 0)),
        "rows_with_canon": int(event_signup_load_meta.get("rows_with_canon", len(event_signups_df))),
        "total_entries": int(len(event_signups_df)),
        "applied_entries": 0,
        "ignored_entries": 0,
        "hard_commitments": hard_signup_total,
    }

    if not event_signups_df.empty:
        seen_extra = set()
        for row in event_signups_df.itertuples(index=False):
            display = getattr(row, "PlayerName", "") or ""
            canon = getattr(row, "canon", pd.NA)
            group = (getattr(row, "Group", "") or "").strip().upper()
            role = (getattr(row, "Role", "") or "").strip().title()
            source = (getattr(row, "Source", "") or "manual_event_signup").strip()
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

    signups_meta["hard_commitments_applied"] = len(forced_signups)
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
    signup_pool_stats = {
        "source": signups_meta["source"],
        "raw_rows": signups_meta["raw_rows"],
        "rows_with_playername": signups_meta["rows_with_playername"],
        "rows_with_canon": signups_meta["rows_with_canon"],
        "total_entries": signups_meta["total_entries"],
        "applied_entries": signups_meta["applied_entries"],
        "ignored_entries": signups_meta["ignored_entries"],
        "hard_commitments_total": hard_signup_total,
        "hard_commitments_applied": signups_meta["hard_commitments_applied"],
        "hard_commitments_invalid": signups_meta["hard_commitments_invalid"],
        "hard_commitments_overbooked": signups_meta["hard_commitments_overbooked"],
        "hard_commitments_missing_from_roster": hard_missing_from_roster,
        "in_roster_hard_commitments": forced_in_roster,
        "extra_entries_total": signups_meta["extra_entries_total"],
        "extra_entries_by_group": signups_meta["extra_entries_by_group"],
    }

    callup_stats = {
        "schema": 1,
        "recommended_total": int(callup_recommended_total),
        "reasons": callup_reason_counts,
        "rules": CALLUP_RULES,
    }

    json_payload = {
        "generated_at": datetime.now(TZ).isoformat(),
        "schema": schema_block,
        "signup_pool": signup_pool_stats,
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
    }

    _write_outputs(out_dir, out_df, json_payload)


if __name__ == "__main__":
    main()
