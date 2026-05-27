import argparse
import logging
import sys

from app.forecasting import validate_forecaster


def main() -> int:
    parser = argparse.ArgumentParser(description="Forecaster validation")
    parser.add_argument(
        "--no-trends",
        action="store_true",
        help="Skip the Google Trends portion (synthetic only)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    print("=" * 70)
    print("FORECASTER VALIDATION")
    print("=" * 70)

    report = validate_forecaster(include_real_world=not args.no_trends)

    print("\n--- Synthetic patterns ---")
    for case in report.synthetic_cases:
        marker = "PASS" if case.passed else "FAIL"
        print(f"  [{marker}] {case.name:30} {case.detail}")

    if report.real_world_cases:
        print("\n--- Real-world (Google Trends) ---")
        for case in report.real_world_cases:
            marker = "PASS" if case.passed else "FAIL"
            print(f"  [{marker}] {case.name:30} {case.detail}")
    else:
        print("\n--- Real-world (Google Trends): skipped ---")

    print()
    print("=" * 70)
    print(f"SUMMARY: {report.total_passed}/{report.total_cases} cases passed")
    print("=" * 70)

    return 0 if report.total_passed == report.total_cases else 1


if __name__ == "__main__":
    sys.exit(main())
