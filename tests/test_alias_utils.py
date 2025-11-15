from __future__ import annotations

import pytest

from src.alias_utils import AliasResolutionError, load_alias_map


def _write_aliases(tmp_path, rows, header=("from_name", "to_name")):
    path = tmp_path / "aliases.csv"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(",".join(header) + "\n")
        for row in rows:
            fh.write(",".join(map(str, row)) + "\n")
    return path


def test_resolve_alias_map_simple_chain(tmp_path):
    path = _write_aliases(tmp_path, [("Alpha", "Bravo")])
    mapping = load_alias_map(str(path))
    assert mapping == {"alpha": "bravo"}


def test_resolve_alias_map_transitive_chain(tmp_path):
    path = _write_aliases(tmp_path, [
        ("Alpha", "Bravo"),
        ("Bravo", "Charlie"),
    ])
    mapping = load_alias_map(str(path))
    assert mapping == {"alpha": "charlie", "bravo": "charlie"}


def test_resolve_alias_map_cycle_raises(tmp_path):
    path = _write_aliases(tmp_path, [
        ("Alpha", "Bravo"),
        ("Bravo", "Alpha"),
    ])
    with pytest.raises(AliasResolutionError):
        load_alias_map(str(path))


def test_resolve_alias_map_depth_guard(tmp_path):
    rows = [(f"P{i}", f"P{i + 1}") for i in range(5)]
    path = _write_aliases(tmp_path, rows)
    with pytest.raises(AliasResolutionError):
        load_alias_map(str(path), max_depth=2)

    # ensure custom depth allows resolution
    mapping = load_alias_map(str(path), max_depth=10)
    expected_last = f"p{len(rows)}"
    assert mapping["p0"] == expected_last
    assert mapping["p3"] == expected_last


def test_load_alias_map_with_playername_alias_header(tmp_path):
    path = _write_aliases(
        tmp_path,
        [
            ("DarkSchredder", "DarkWerwolf", 1),
            ("Foo", "Bar", 0),
        ],
        header=("PlayerName", "Alias", "Active"),
    )
    mapping = load_alias_map(str(path))
    assert mapping == {"darkwerwolf": "darkschredder"}


def test_load_alias_map_with_alias_playername_header(tmp_path):
    path = _write_aliases(
        tmp_path,
        [
            ("DarkWerwolf", "DarkSchredder"),
        ],
        header=("Alias", "PlayerName"),
    )
    mapping = load_alias_map(str(path))
    assert mapping == {"darkwerwolf": "darkschredder"}
