from __future__ import annotations

import logging
import sys

from app import db
from app.reporting import generate_report


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s %(message)s",
)


def main() -> int:
    db.init_db()

    print("Generating report from current DB state...")
    print()

    result = generate_report()

    print(f"Report generated in {result['duration_seconds']}s ({result['size_kb']} KB)")
    print()
    print(f"  Markdown: {result['md_path']}")
    print(f"  HTML:     {result['html_path']}")
    print()
    print(f"  Latest:   {result['latest_md']}")
    print(f"            {result['latest_html']}")
    print()
    print("View in browser:")
    print(f"  file:///{result['html_path']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
