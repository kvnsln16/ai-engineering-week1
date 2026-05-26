import logging

from app.connectors.tier2 import TIER2_CONNECTORS


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    total = 0
    for connector in TIER2_CONNECTORS:
        records = connector.collect()
        print(f"[{connector.name:12}] {len(records):3d} records")
        total += len(records)

    print("---")
    print(f"Total: {total} records across {len(TIER2_CONNECTORS)} sources.")

    for connector in TIER2_CONNECTORS:
        sample = connector.collect()[:1]
        if sample:
            print("\nExample record:")
            for k, v in sample[0].items():
                if k == "raw":
                    continue
                print(f"  {k:13}: {v!r}")
            break


if __name__ == "__main__":
    main()
