"""Build small in-memory RouteGraph instances for optimality oracle tests."""

from __future__ import annotations

import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from main import RouteGraph, TrainEdge  # noqa: E402

StationDef = tuple[str, str, float, float]
EdgeDef = tuple[str, str, float, float, str, time, time, str, str]


def build_graph(stations: list[StationDef], edges: list[EdgeDef]) -> RouteGraph:
    graph = RouteGraph()
    for code, name, lat, lon in stations:
        graph.stations[code] = {"name": name, "lat": lat, "lon": lon}

    for fc, tc, ride_min, price_rub, train_no, dep, arr, reg_type, reg_desc in edges:
        edge = TrainEdge(
            to_code=tc,
            train_no=train_no,
            departure_time=dep,
            arrival_time=arr,
            ride_min=ride_min,
            price_rub=price_rub,
            regularity_type=reg_type,
            regularity_desc=reg_desc,
        )
        graph.edges[fc].append(edge)
        graph.has_outgoing.add(fc)
        graph.has_incoming.add(tc)

    graph._has_schedules = any(dep != time(0, 0) for *_, dep, _, _, _ in edges)
    graph._build_spatial_indexes()
    return graph


def endpoint(graph: RouteGraph, code: str, distance_m: int = 0) -> dict:
    info = graph.stations[code]
    return {
        "uic_code": code,
        "name": info["name"],
        "lat": info["lat"],
        "lon": info["lon"],
        "distance_m": distance_m,
    }


def train_uic_chain(route: dict) -> list[str]:
    trains = [leg for leg in route["legs"] if leg["type"] == "train"]
    if not trains:
        return []
    chain = [trains[0]["from_code"]]
    for leg in trains:
        chain.append(leg["to_code"])
    return chain


def diamond_graph() -> RouteGraph:
    """Five-station graph with a faster multi-leg path than the direct edge.

    Optimal by time: S1 -> S3 -> S4 -> S5 (150 min incl. 2 transfers).
    Optimal by cost: same path (180 rub).
    Direct S1 -> S5 exists but is worse on both criteria.
    """
    stations: list[StationDef] = [
        ("S1", "Alpha", 55.00, 37.00),
        ("S2", "Bravo", 55.01, 37.00),
        ("S3", "Charlie", 55.00, 37.01),
        ("S4", "Delta", 55.01, 37.01),
        ("S5", "Echo", 55.02, 37.01),
    ]
    every_day = ("EveryDay", "ежедневно")
    t0 = time(0, 0)
    edges: list[EdgeDef] = [
        ("S1", "S2", 100, 100, "T12", t0, t0, *every_day),
        ("S1", "S3", 50, 80, "T13", t0, t0, *every_day),
        ("S2", "S5", 50, 100, "T25", t0, t0, *every_day),
        ("S3", "S4", 40, 50, "T34", t0, t0, *every_day),
        ("S4", "S5", 30, 50, "T45", t0, t0, *every_day),
        ("S1", "S5", 200, 300, "T15", t0, t0, *every_day),
    ]
    return build_graph(stations, edges)


def scheduled_triangle_graph() -> RouteGraph:
    """Scheduled graph: connection via S2 beats a late direct train."""
    stations: list[StationDef] = [
        ("S1", "Alpha", 55.00, 37.00),
        ("S2", "Bravo", 55.01, 37.00),
        ("S5", "Echo", 55.02, 37.01),
    ]
    every_day = ("EveryDay", "ежедневно")
    edges: list[EdgeDef] = [
        ("S1", "S2", 120, 100, "T12", time(8, 0), time(10, 0), *every_day),
        ("S2", "S5", 30, 50, "T25", time(10, 30), time(11, 0), *every_day),
        ("S1", "S5", 300, 200, "T15", time(9, 0), time(14, 0), *every_day),
    ]
    return build_graph(stations, edges)
