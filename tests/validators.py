"""Shared invariant and expectation checks for /search responses."""

MAX_WALK_M = 100_000
MAX_ACCESS_M = 600_000  # taxi egress / remote fallback can exceed 100 km
MAX_TRAIN_LEGS = 3
MAX_TRANSFERS = 2


def train_legs(route: dict) -> list[dict]:
    return [leg for leg in route.get("legs", []) if leg.get("type") == "train"]


def assert_route_invariants(route: dict) -> None:
    assert route["total_duration_min"] > 0
    assert route["total_price_rub"] >= 0
    assert 0 <= route["transfers"] <= MAX_TRANSFERS

    legs = route.get("legs", [])
    assert legs, "route must have legs"

    trains = train_legs(route)
    assert len(trains) <= MAX_TRAIN_LEGS
    assert route["transfers"] == max(0, len(trains) - 1)

    for leg in legs:
        if leg["type"] == "walk":
            dist = leg.get("distance_m")
            if dist is not None:
                assert 0 <= dist <= MAX_ACCESS_M
        if leg["type"] == "train":
            assert leg.get("from_code")
            assert leg.get("to_code")
            assert leg["duration_min"] > 0
            assert leg["price_rub"] >= 0

    for i in range(1, len(trains)):
        prev, cur = trains[i - 1], trains[i]
        assert prev["to_code"] == cur["from_code"], (
            f"train legs not connected: {prev['to_code']} != {cur['from_code']}"
        )

    if route.get("scheduled"):
        for leg in trains:
            assert "boarding_label" in leg
            assert "arrival_label" in leg


def assert_response_invariants(data: dict) -> None:
    routes = data.get("routes", [])
    assert routes, "expected at least one route"
    for route in routes:
        assert_route_invariants(route)


def assert_expectations(data: dict, expect: dict) -> None:
    routes = data.get("routes", [])

    min_routes = expect.get("min_routes")
    if min_routes is not None:
        assert len(routes) >= min_routes

    max_routes = expect.get("max_routes")
    if max_routes is not None:
        assert len(routes) <= max_routes

    if not routes:
        return

    best = routes[0]

    for key in ("scheduled",):
        if key in expect:
            assert best.get(key) == expect[key], f"{key}: {best.get(key)} != {expect[key]}"

    transfers = best["transfers"]
    if "min_transfers" in expect:
        assert transfers >= expect["min_transfers"]
    if "max_transfers" in expect:
        assert transfers <= expect["max_transfers"]

    dur = best["total_duration_min"]
    if "duration_min" in expect:
        lo, hi = expect["duration_min"]
        assert lo <= dur <= hi, f"duration {dur} not in [{lo}, {hi}]"

    if "min_duration_min" in expect:
        assert dur >= expect["min_duration_min"]
    if "max_duration_min" in expect:
        assert dur <= expect["max_duration_min"]

    if expect.get("require_train_legs"):
        assert train_legs(best), "expected at least one train leg"

    if "min_price_rub" in expect:
        assert best["total_price_rub"] >= expect["min_price_rub"]
    if "max_price_rub" in expect:
        assert best["total_price_rub"] <= expect["max_price_rub"]
