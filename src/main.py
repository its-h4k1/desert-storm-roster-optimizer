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
    if "Active" not in df.columns:
        df["Active"] = 1
    df["Active"] = pd.to_numeric(df["Active"], errors="coerce").fillna(0).astype(int).clip(0, 1)
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
    if "Active" not in df.columns:
        df["Active"] = 1
    df["Active"] = pd.to_numeric(df["Active"], errors="coerce").fillna(0).astype(int)
    df = df[df["Active"] == 1].copy()
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
        if getattr(row, "Active", 0) != 1:
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
    latest_dir = Path("out")
    latest_dir.mkdir(parents=True, exist_ok=True)

    csv_cols = ["PlayerName", "Group", "Role", "NoShowOverall", "NoShowRolling"]
    roster_df[csv_cols].to_csv(latest_dir / "latest.csv", index=False)
    (out_dir / "roster.csv").write_text((roster_df[csv_cols]).to_csv(index=False), encoding="utf-8")

    (latest_dir / "latest.json").write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "roster.json").write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] wrote {latest_dir/'latest.csv'} and {latest_dir/'latest.json'}")
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
    if args.absences:
        try:
            abs_df = _load_absences(args.absences)
            print(f"[ok] absences loaded: {len(abs_df)} Einträge")
        except Exception as e:
            print(f"[warn] absences nicht nutzbar: {e}")

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

    # 3) Allianz joinen (nur Active==1 als Kandidaten)
    pool = alliance_df.merge(
        role_probs.drop(columns=["PlayerName"], errors="ignore"),
        on="canon",
        how="left",
    )

    pool["InAlliance"] = pool["Active"].fillna(0).astype(int)
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

    # 5) Input für Builder
    probs_for_builder = pd.DataFrame({
        "PlayerName": pool["canon"],
        "p_start": pool["p_start"].fillna(p0),
        "p_sub": pool["p_sub"].fillna(p0),
        "PrefGroup": pool.get("PrefGroup", pd.Series([pd.NA]*len(pool))),
        "PrefMode": pool.get("PrefMode", pd.Series([pd.NA]*len(pool))),
        "PrefBoost": pool.get("PrefBoost", pd.Series([pd.NA]*len(pool))),
        "events_seen": pool["events_seen"],
        "risk_penalty": pool["risk_penalty"],
    })

    # 6) Roster bauen
    roster = build_deterministic_roster(probs_for_builder)  # PlayerName = canon

    # 7) Anzeige + Kennzahlen
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

    out_df = roster[
        [
            "DisplayName",
            "PlayerName",
            "Group",
            "Role",
            "NoShowOverall",
            "NoShowRolling",
            "LastSeenDate",
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

    schema_block = {
        "version": 2,
        "csv": ["PlayerName", "Canonical", "Group", "Role", "NoShowOverall", "NoShowRolling", "LastSeenDate"],
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
    }

    players_payload = []
    for row in out_df.itertuples(index=False):
        entry = {
            "display": row.PlayerName,
            "canon": row.Canonical,
            "group": row.Group,
            "role": row.Role,
            "noshow_overall": _float_default(row.NoShowOverall, 0.0),
            "noshow_rolling": _float_default(row.NoShowRolling, 0.0),
            "last_seen": row.LastSeenDate,
            "events_seen": _int_default(row.events_seen, 0),
            "noshow_count": _int_default(row.noshow_count, 0),
            "risk_penalty": _float_default(row.risk_penalty, 0.0),
            "score": _float_default(row.risk_penalty, 0.0),
        }
        if cfg.EB_ENABLE:
            entry["eb"] = {
                "p0": float(p0),
                "n0": float(cfg.EB_N0),
                "p_hat": _float_or_none(row.eb_p_hat),
                "sigma": _float_or_none(row.eb_sigma),
            }
        players_payload.append(entry)

    json_payload = {
        "generated_at": datetime.now(TZ).isoformat(),
        "schema": schema_block,
        "groups": {
            "A": {"Start": _by("A", "Start"), "Ersatz": _by("A", "Ersatz")},
            "B": {"Start": _by("B", "Start"), "Ersatz": _by("B", "Ersatz")},
        },
        "players": players_payload,
    }

    _write_outputs(out_dir, out_df, json_payload)


if __name__ == "__main__":
    main()
