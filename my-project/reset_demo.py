from __future__ import annotations

import sys
from pathlib import Path


DB_PATH = Path("db") / "app.sqlite"


def main() -> int:
    if not DB_PATH.exists():
        print(f"No database found at {DB_PATH} — nothing to reset.")
        return 0

    size_kb = DB_PATH.stat().st_size / 1024

    print(f"About to delete: {DB_PATH} ({size_kb:.1f} KB)")
    print("All collected signals, dedup history, and enrichments will be lost.")
    print()
    confirm = input("Type 'yes' to confirm: ").strip().lower()

    if confirm != "yes":
        print("Cancelled.")
        return 1

    DB_PATH.unlink()
    print(f"Deleted {DB_PATH}")
    print()
    print("Next run will start fresh. Run:")
    print("  python run_orchestrator.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())