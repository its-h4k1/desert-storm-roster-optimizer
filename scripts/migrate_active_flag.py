#!/usr/bin/env python3
"""Convert legacy `Active` columns to `InAlliance` in CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rename the legacy Active column to InAlliance in-place."
    )
    parser.add_argument("csv", help="Path to the CSV file (e.g. data/alliance.csv)")
    parser.add_argument(
        "--output",
        help="Optional output path. If omitted, the source file is overwritten.",
        default="",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Write a <file>.bak backup before overwriting the input (only used without --output).",
    )
    return parser.parse_args()


def write_backup(path: Path) -> None:
    backup_path = path.with_suffix(path.suffix + ".bak")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[ok] backup written to {backup_path}")


def main() -> None:
    args = parse_args()
    source_path = Path(args.csv)
    if not source_path.exists():
        raise SystemExit(f"[fatal] file not found: {source_path}")

    df = pd.read_csv(source_path, dtype=str)
    if "InAlliance" in df.columns:
        print("[info] column InAlliance already present – nothing to do.")
        if args.output:
            out_path = Path(args.output)
            df.to_csv(out_path, index=False)
            print(f"[ok] wrote {out_path}")
        return

    if "Active" not in df.columns:
        raise SystemExit("[fatal] neither InAlliance nor Active found in CSV")

    df = df.rename(columns={"Active": "InAlliance"})
    df["InAlliance"] = (
        pd.to_numeric(df["InAlliance"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    )

    out_path = Path(args.output) if args.output else source_path
    if not args.output and args.backup:
        write_backup(source_path)
    df.to_csv(out_path, index=False)
    print(f"[ok] wrote {out_path}")


if __name__ == "__main__":
    main()
