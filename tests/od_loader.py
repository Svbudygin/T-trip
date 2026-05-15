"""Load OD test cases and build API payloads."""

from __future__ import annotations

from pathlib import Path

import yaml

SUITE_PATH = Path(__file__).parent / "od_suite.yaml"


def load_od_cases() -> list[dict]:
    with SUITE_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    defaults = data.get("defaults", {})
    cases = data["cases"]
    for case in cases:
        for key, value in defaults.items():
            case.setdefault(key, value)
    return cases


def build_payload(case: dict) -> dict:
    payload = {
        "from_lat": case["from_lat"],
        "from_lon": case["from_lon"],
        "to_lat": case["to_lat"],
        "to_lon": case["to_lon"],
        "optimize_by": case.get("optimize_by", "time"),
        "min_transfer_min": case.get("min_transfer_min", 15),
    }
    if case.get("departure_date") is not None:
        payload["departure_date"] = case["departure_date"]
    if case.get("departure_time") is not None:
        payload["departure_time"] = case["departure_time"]
    return payload
