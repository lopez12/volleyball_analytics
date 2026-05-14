"""Export all tables from volleyball.db to CSV files in data/."""

import csv
import sqlite3
from pathlib import Path

DB_PATH = Path("data/volleyball.db")
OUT_DIR = Path("data")


def export_table(conn, table: str, out_path: Path) -> int:
    cursor = conn.execute(f"SELECT * FROM {table}")  # noqa: S608 – local read-only DB
    headers = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return len(rows)


def main():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}. Run generate.py first.")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        tables = ["matches", "team_match_stats", "player_match_stats"]
        for table in tables:
            out_path = OUT_DIR / f"{table}.csv"
            count = export_table(conn, table, out_path)
            print(f"  {table}.csv  ({count} rows)  →  {out_path}")
    finally:
        conn.close()

    print("\nDone. Open the CSV files in Excel or any spreadsheet app.")


if __name__ == "__main__":
    main()
