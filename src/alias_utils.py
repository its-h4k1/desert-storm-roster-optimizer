from __future__ import annotations

"""Utilities for loading and resolving player aliases."""

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set, List, Tuple
import warnings

import pandas as pd

from .utils import canonical_name

DEFAULT_MAX_ALIAS_DEPTH = 64


class AliasResolutionError(ValueError):
    """Raised when alias data cannot be resolved to a canonical mapping."""


@dataclass(frozen=True)
class _AliasColumns:
    source: str
    target: str
    active: Optional[str]


def _pick_column(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    lower_to_original = {c.lower(): c for c in columns}
    for candidate in candidates:
        lowered = candidate.lower()
        if lowered in lower_to_original:
            return lower_to_original[lowered]
    return None


def _detect_columns(df: pd.DataFrame) -> _AliasColumns:
    source = _pick_column(df.columns, [
        "alias",
        "from_name",
        "from",
        "src",
        "playername",
        "aliasfrom",
        "alias_from",
    ])
    target = _pick_column(df.columns, [
        "canonical",
        "to_name",
        "to",
        "dst",
        "alias",
        "aliasto",
        "alias_to",
    ])
    if source is None or target is None:
        raise AliasResolutionError(
            "aliases.csv benötigt (from_name,to_name) ODER (PlayerName,Alias)"
        )

    active = _pick_column(df.columns, ["active", "enabled"])
    return _AliasColumns(source=source, target=target, active=active)


def _prepare_raw_mapping(df: pd.DataFrame, cols: _AliasColumns) -> Dict[str, str]:
    use_cols = [cols.source, cols.target]
    if cols.active:
        use_cols.append(cols.active)

    df = df[use_cols].copy()
    df[cols.source] = df[cols.source].astype(str).map(canonical_name)
    df[cols.target] = df[cols.target].astype(str).map(canonical_name)

    if cols.active:
        df[cols.active] = (
            pd.to_numeric(df[cols.active], errors="coerce").fillna(1).astype(int)
        )
        df = df[df[cols.active] != 0]

    df = df.dropna(subset=[cols.source, cols.target])
    df = df[df[cols.source] != ""]

    # "Erste Zeile gewinnt"
    df = df.drop_duplicates(subset=[cols.source], keep="first")

    mapping: Dict[str, str] = {}
    for _, row in df.iterrows():
        src = row[cols.source]
        dst = row[cols.target]
        if src == dst:
            continue
        mapping[src] = dst
    return mapping


def _prune_cycles(raw_map: Dict[str, str]) -> Tuple[Dict[str, str], Set[str]]:
    """Entfernt Alias-Regeln, die Zyklen erzeugen.

    Statt den gesamten Import scheitern zu lassen, werden nur die direkt
    betroffenen Quellen entfernt. So bleiben valide Aliase verfügbar und
    Problemfälle können dennoch identifiziert werden.
    """

    graph = dict(raw_map)
    visited: Set[str] = set()
    active: Set[str] = set()
    cycle_nodes: Set[str] = set()

    def dfs(node: str, stack: List[str]):
        if node in visited or node in cycle_nodes:
            return
        if node in active:
            # Zyklus gefunden → alle Nodes ab erstem Auftreten im Stack markieren
            try:
                start = stack.index(node)
            except ValueError:
                start = 0
            cycle_nodes.update(stack[start:])
            return

        active.add(node)
        stack.append(node)
        target = graph.get(node)
        if target is not None:
            dfs(target, stack)
        stack.pop()
        active.remove(node)
        visited.add(node)

    for node in list(graph.keys()):
        if node not in visited:
            dfs(node, [])

    if not cycle_nodes:
        return graph, set()

    for node in cycle_nodes:
        graph.pop(node, None)

    return graph, cycle_nodes


def resolve_alias_map(
    raw_map: Dict[str, str],
    *,
    max_depth: int = DEFAULT_MAX_ALIAS_DEPTH,
) -> Dict[str, str]:
    """
    Resolve aliases transitively with cycle / depth protection.

    Args:
        raw_map: Mapping of canonical alias -> canonical target.
        max_depth: Maximum number of steps that may be followed before raising.

    Returns:
        A mapping where each key points directly to its canonical representative.

    Raises:
        AliasResolutionError: If a cycle is detected or the maximum depth is exceeded.
    """
    if max_depth <= 0:
        raise AliasResolutionError("max_depth muss > 0 sein")

    resolved: Dict[str, str] = {}

    for source in raw_map.keys():
        current = source
        seen: Set[str] = {source}

        for steps in range(max_depth):
            target = raw_map.get(current)
            if target is None or target == current:
                resolved[source] = current
                break
            if target in seen:
                # Explizit fehlschlagen statt stillschweigend abbrechen – sonst bliebe der
                # Konflikt unentdeckt und würde in den Daten fortbestehen.
                raise AliasResolutionError(
                    f"Alias-Zyklus entdeckt: {source} → ... → {target}"
                )
            seen.add(target)
            current = target
        else:
            # Auch hier lieber ein klarer Fehler als ein stilles "return cur" nach 64 Schritten.
            raise AliasResolutionError(
                f"Alias-Kette zu lang (>{max_depth} Schritte) ab {source}"
            )

    return {k: v for k, v in resolved.items() if k != v}


def load_alias_map(path: str, *, max_depth: int = DEFAULT_MAX_ALIAS_DEPTH) -> Dict[str, str]:
    """Load aliases from ``path`` and resolve them transitively."""
    df = pd.read_csv(path, comment="#", dtype=str)
    if df.empty:
        return {}

    cols = _detect_columns(df)
    raw_map = _prepare_raw_mapping(df, cols)
    if not raw_map:
        return {}

    clean_map, cycle_nodes = _prune_cycles(raw_map)
    if cycle_nodes:
        preview = ", ".join(sorted(cycle_nodes)[:5])
        more = "" if len(cycle_nodes) <= 5 else ", …"
        warnings.warn(
            (
                f"{len(cycle_nodes)} Alias-Regeln wegen Zyklus entfernt: "
                f"{preview}{more}"
            ),
            RuntimeWarning,
            stacklevel=2,
        )

    return resolve_alias_map(clean_map, max_depth=max_depth)


__all__ = ["AliasResolutionError", "DEFAULT_MAX_ALIAS_DEPTH", "load_alias_map", "resolve_alias_map"]
