import logging

from app.scheduler.jobs import run_all_collectors

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s %(name)s: %(message)s",
)

result = run_all_collectors()

print()
print("=" * 50)
print("SUMMARY")
print("=" * 50)
print(f"Connectors:     {result['collector_count']}")
print(f"Total fetched:  {result['total_fetched']}")
print(f"Total new:      {result['total_new']}")
print(f"Failures:       {result['total_failures']}")
print(f"Duration:       {result['duration_seconds']}s")
print()
print("Per-connector breakdown:")
for c in result["per_collector"]:
    status = "OK" if not c["error"] else f"ERROR: {c['error'][:60]}"
    print(f"  {c['name']:20} fetched={c['fetched']:3}  new={c['new']:3}  {status}")
print()
print("Enrichment:")
e = result["enrichment"]
print(f"  Processed:    {e['processed']}")
print(f"  Errors:       {e['errors']}")
print(f"  Speed:        {e['signals_per_second']} signals/sec")
print(f"  Duration:     {e['duration_seconds']}s")