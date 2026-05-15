"""Synthetic-graph oracle tests: known shortest paths for RouteGraph.search()."""

from __future__ import annotations

import sys
from datetime import date, time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from main import DEFAULT_MIN_TRANSFER_MIN, OptimizeBy  # noqa: E402

from synthetic_graph import (  # noqa: E402
    diamond_graph,
    endpoint,
    scheduled_triangle_graph,
    train_uic_chain,
)


OPTIMAL_DIAMOND_CHAIN = ["S1", "S3", "S4", "S5"]
OPTIMAL_DIAMOND_TIME = 50 + 40 + 30 + 2 * DEFAULT_MIN_TRANSFER_MIN  # 150
OPTIMAL_DIAMOND_COST = 80 + 50 + 50  # 180


@pytest.fixture
def diamond():
    return diamond_graph()


def _search(diamond, optimize_by: OptimizeBy):
    return diamond.search(
        from_stations=[endpoint(diamond, "S1")],
        to_stations=[endpoint(diamond, "S5")],
        optimize_by=optimize_by,
        max_routes=5,
    )


def test_static_time_finds_known_shortest_path(diamond):
    routes = _search(diamond, OptimizeBy.time)
    assert routes, "expected at least one route"

    best = routes[0]
    assert train_uic_chain(best) == OPTIMAL_DIAMOND_CHAIN
    assert best["total_duration_min"] == OPTIMAL_DIAMOND_TIME
    assert best["transfers"] == 2


def test_static_cost_finds_known_cheapest_path(diamond):
    routes = _search(diamond, OptimizeBy.cost)
    assert routes, "expected at least one route"

    best = routes[0]
    assert train_uic_chain(best) == OPTIMAL_DIAMOND_CHAIN
    assert best["total_price_rub"] == OPTIMAL_DIAMOND_COST
    assert best["transfers"] == 2


def test_static_time_beats_direct_and_one_transfer_alternatives(diamond):
    routes = _search(diamond, OptimizeBy.time)
    durations = [r["total_duration_min"] for r in routes]

    assert OPTIMAL_DIAMOND_TIME in durations
    assert 200 not in durations[:1]  # direct S1->S5 must not rank first
    assert durations[0] == min(durations)


def test_single_leg_has_no_transfer_penalty(diamond):
    routes = diamond.search(
        from_stations=[endpoint(diamond, "S1")],
        to_stations=[endpoint(diamond, "S3")],
        optimize_by=OptimizeBy.time,
        max_routes=1,
    )
    assert len(routes) == 1
    assert train_uic_chain(routes[0]) == ["S1", "S3"]
    assert routes[0]["total_duration_min"] == 50
    assert routes[0]["transfers"] == 0


def test_scheduled_mode_respects_timetable_waits():
    graph = scheduled_triangle_graph()
    routes = graph.search(
        from_stations=[endpoint(graph, "S1")],
        to_stations=[endpoint(graph, "S5")],
        optimize_by=OptimizeBy.time,
        max_routes=3,
        departure_date=date(2026, 5, 26),
        departure_time=time(7, 0),
    )
    assert routes, "expected scheduled route"

    best = routes[0]
    assert best["scheduled"] is True
    assert train_uic_chain(best) == ["S1", "S2", "S5"]
    # 07:00 start, 120 min ride -> 10:00, +15 min transfer -> 10:30 board, +30 min -> 11:00
    assert best["total_duration_min"] == 240
