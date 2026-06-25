"""Export all tables from each dataset's volleyball.db to CSV files alongside it.

Walks every per-dataset database under data/<team>/<tournament>/volleyball.db
and writes matches.csv, team_match_stats.csv, and player_match_stats.csv into
the same folder.
"""

import csv
import sqlite3
from pathlib import Path

DATA_ROOT = Path("data")
TABLES = ["matches", "team_match_stats", "player_match_stats"]


def export_table(conn, table: str, out_path: Path) -> int:
    cursor = conn.execute(f"SELECT * FROM {table}")  # noqa: S608 – local read-only DB
    headers = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return len(rows)


def export_dataset(db_path: Path) -> None:
    """Export every table of one dataset database into CSVs beside it."""
    out_dir = db_path.parent
    conn = sqlite3.connect(db_path)
    try:
        for table in TABLES:
            out_path = out_dir / f"{table}.csv"
            count = export_table(conn, table, out_path)
            print(f"  {out_path}  ({count} rows)")
    finally:
        conn.close()


def main():
    if not DATA_ROOT.is_dir():
        print(f"Data folder not found at {DATA_ROOT}. Run generate.py first.")
        return

    db_paths = sorted(DATA_ROOT.glob("*/*/volleyball.db"))
    if not db_paths:
        print(f"No dataset databases found under {DATA_ROOT}. Run generate.py first.")
        return

    for db_path in db_paths:
        export_dataset(db_path)

    print("\nDone. Open the CSV files in Excel or any spreadsheet app.")


if __name__ == "__main__":
    main()
