"""Print the measured static vs dynamic comparison (no fabricated values)."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", default="results/static/summary.json")
    parser.add_argument("--dynamic", default="results/dynamic/summary.json")
    args = parser.parse_args()
    static = json.loads(Path(args.static).read_text(encoding="utf-8"))
    dynamic = json.loads(Path(args.dynamic).read_text(encoding="utf-8"))
    fields = (
        ("Unique datagrams sent", "sent_unique"),
        ("Acknowledged", "acknowledged"),
        ("Unrecovered", "unrecovered"),
        ("Initial attempt timeout %", "initial_attempt_timeout_pct"),
        ("Delivered before repair", "delivered_before_restore"),
        ("Recovery time ms", "recovery_time_ms"),
        ("Mean delivery latency ms", "mean_delivery_latency_ms"),
        ("Max delivery latency ms", "max_delivery_latency_ms"),
    )
    print("Metric                         Static          Dynamic")
    print("-" * 59)
    for label, key in fields:
        print("{:<30} {:<15} {}".format(label, static.get(key), dynamic.get(key)))


if __name__ == "__main__":
    main()
