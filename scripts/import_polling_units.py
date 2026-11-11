#!/usr/bin/env python3
"""Import a polling-unit CSV straight into the SQLite database.

The admin endpoint POST /api/admin/import-polling-units is the normal route, but
it caps uploads at 20 MB and a nationwide INEC extract is larger. This script
validates each row with the same Pydantic model the API uses, derives the same
stable id, and writes in one transaction.

Usage:
    python scripts/import_polling_units.py data/polling_units.inec.csv
    python scripts/import_polling_units.py --db data/naijavote.db parts/*.csv

Invalid rows abort the whole import (nothing is written) and are reported with
their line numbers, matching the API's all-or-nothing behaviour.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

REQUIRED = {"state", "lga", "ward", "name", "code", "source", "source_url", "verified_at"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="CSV files to import")
    parser.add_argument(
        "--db",
        default=os.getenv("DATABASE_PATH", "data/naijavote.db"),
        help="SQLite database path (default: DATABASE_PATH or data/naijavote.db)",
    )
    parser.add_argument("--batch", type=int, default=2000)
    args = parser.parse_args()

    # backend.app resolves DB_PATH at import time, so set it first.
    os.environ["DATABASE_PATH"] = str(Path(args.db).resolve())
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from backend.app import UnitUpload, _unit_row, db, init_db  # noqa: E402

    init_db()

    rows: list[tuple] = []
    errors: list[str] = []
    rejected = 0
    for file in args.files:
        with open(file, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED - set(reader.fieldnames or [])
            if missing:
                print(f"{file}: missing columns {', '.join(sorted(missing))}", file=sys.stderr)
                return 2
            for line, raw in enumerate(reader, start=2):
                for key in ("latitude", "longitude"):
                    if raw.get(key) in ("", None):
                        raw[key] = None
                if raw.get("accessibility") in ("", None):
                    raw["accessibility"] = "unknown"
                try:
                    rows.append(_unit_row(UnitUpload(**raw)))
                except Exception as exc:  # pydantic ValidationError and friends
                    rejected += 1
                    if len(errors) < 10:
                        errors.append(f"{file}:{line} ({raw.get('code')}): {exc}")

    if rejected:
        print(f"Rejected {rejected} row(s); nothing imported:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    for start in range(0, len(rows), args.batch):
        with db() as con:
            con.executemany(
                "INSERT OR REPLACE INTO polling_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                rows[start : start + args.batch],
            )

    with db() as con:
        total = con.execute("SELECT count(*) FROM polling_units").fetchone()[0]
    print(f"Imported {len(rows)} rows into {os.environ['DATABASE_PATH']} — polling_units now {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
