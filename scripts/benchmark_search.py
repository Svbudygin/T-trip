#!/usr/bin/env python3
"""Benchmark POST /search latency (p50/p95) for kt3 report."""

from __future__ import annotations

import argparse
import os
import statistics
import time

import requests

DEFAULT_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")

PAYLOADS = [
    {
        "from_lat": 55.7558,
        "from_lon": 37.6173,
        "to_lat": 59.9343,
        "to_lon": 30.3351,
        "optimize_by": "time",
        "departure_date": "2026-05-26",
        "departure_time": "08:00",
    },
    {
        "from_lat": 55.7558,
        "from_lon": 37.6173,
        "to_lat": 55.7963,
        "to_lon": 49.1088,
        "optimize_by": "time",
        "departure_date": "2026-05-26",
        "departure_time": "08:00",
    },
    {
        "from_lat": 55.7558,
        "from_lon": 37.6173,
        "to_lat": 59.9343,
        "to_lon": 30.3351,
        "optimize_by": "time",
    },
]


def percentile(sorted_values: list[float], p: float) -> float:
    idx = int(len(sorted_values) * p)
    idx = min(idx, len(sorted_values) - 1)
    return sorted_values[idx]


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark /search latency")
    parser.add_argument("-n", "--count", type=int, default=50, help="total requests")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    url = f"{args.url}/search"
    times_ms: list[float] = []

    for i in range(args.count):
        payload = PAYLOADS[i % len(PAYLOADS)]
        t0 = time.perf_counter()
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        times_ms.append((time.perf_counter() - t0) * 1000)

    times_ms.sort()
    n = len(times_ms)
    print(f"requests={n}")
    print(f"p50_ms={percentile(times_ms, 0.50):.1f}")
    print(f"p95_ms={percentile(times_ms, 0.95):.1f}")
    print(f"mean_ms={statistics.mean(times_ms):.1f}")
    print(f"min_ms={times_ms[0]:.1f}")
    print(f"max_ms={times_ms[-1]:.1f}")


if __name__ == "__main__":
    main()
