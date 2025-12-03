import os
import heapq
import logging
from enum import Enum
from collections import defaultdict
from math import radians, cos, sin, sqrt, atan2

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text

logger = logging.getLogger("routes")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_NAME = os.getenv("DB_NAME", "train")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

app = FastAPI(title="Путешествия — API маршрутов", version="3.0.0")

WALK_SPEED_M_PER_MIN = 5000 / 60  # 5 km/h -> ~83.3 m/min
TRANSFER_PENALTY_MIN = 30
MAX_TRAIN_LEGS = 3
NEARBY_LIMIT = 10
MAX_WALK_M = 3000  # макс. пешая дистанция до станции (3 км)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    la1, lo1, la2, lo2 = radians(lat1), radians(lon1), radians(lat2), radians(lon2)
    dlat, dlon = la2 - la1, lo2 - lo1
    a = sin(dlat / 2) ** 2 + cos(la1) * cos(la2) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


class OptimizeBy(str, Enum):
    time = "time"
    cost = "cost"


class SearchRequest(BaseModel):
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float
    optimize_by: OptimizeBy = OptimizeBy.time


class RouteGraph:
    """In-memory directed graph of train connections for Dijkstra routing."""

    def __init__(self):
        self.edges: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
        self.stations: dict[str, dict] = {}
        self.has_outgoing: set[str] = set()
        self.has_incoming: set[str] = set()

    async def load(self, session):
        self.edges.clear()
        self.stations.clear()
        self.has_outgoing.clear()
        self.has_incoming.clear()

        rows = await session.execute(
            text("SELECT uic_code, name, lat, lon FROM rzd_stations "
                 "WHERE lat IS NOT NULL AND lon IS NOT NULL")
        )
        for r in rows.mappings():
            self.stations[r["uic_code"]] = {
                "name": r["name"] or "Без названия",
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
            }

        rows = await session.execute(
            text("SELECT from_code, to_code, duration_min, price_rub FROM train_directions")
        )
        n = 0
        for r in rows.mappings():
            fc, tc = r["from_code"], r["to_code"]
            if fc in self.stations and tc in self.stations:
                self.edges[fc].append((tc, float(r["duration_min"]), float(r["price_rub"])))
                self.has_outgoing.add(fc)
                self.has_incoming.add(tc)
                n += 1

        logger.info("RouteGraph: %d stations, %d edges, %d src, %d dst",
                     len(self.stations), n, len(self.has_outgoing), len(self.has_incoming))

    def find_nearest(self, lat: float, lon: float, limit: int,
                     codes_filter: set[str] | None = None,
                     max_dist_m: float = MAX_WALK_M) -> list[dict]:
        buf = []
        for code, info in self.stations.items():
            if codes_filter is not None and code not in codes_filter:
                continue
            dlat = info["lat"] - lat
            dlon = info["lon"] - lon
            buf.append((dlat * dlat + dlon * dlon, code))
        buf.sort()
        out = []
        for _, code in buf[:limit * 3]:
            info = self.stations[code]
            dist = round(haversine_m(lat, lon, info["lat"], info["lon"]))
            out.append({
                "uic_code": code,
                "name": info["name"],
                "lat": info["lat"],
                "lon": info["lon"],
                "distance_m": dist,
            })
        within = [s for s in out if s["distance_m"] <= max_dist_m]
        if within:
            return within[:limit]
        return out[:1]

    # ------------------------------------------------------------------
    # Dijkstra with transfer limit
    # ------------------------------------------------------------------

    def search(self, from_stations: list[dict], to_stations: list[dict],
               optimize_by: OptimizeBy, max_routes: int = 10,
               from_point: dict | None = None, to_point: dict | None = None) -> list[dict]:
        to_codes = {s["uic_code"] for s in to_stations}
        to_info = {s["uic_code"]: s for s in to_stations}
        use_time = (optimize_by == OptimizeBy.time)
        candidates: list[dict] = []

        for src in from_stations:
            src_code = src["uic_code"]
            walk_from = src["distance_m"] / WALK_SPEED_M_PER_MIN

            dist: dict[tuple[str, int], float] = {}
            parent: dict[tuple[str, int], tuple[str, int, float, float]] = {}

            init_w = walk_from if use_time else 0.0
            dist[(src_code, 0)] = init_w
            pq: list[tuple[float, str, int]] = [(init_w, src_code, 0)]

            while pq:
                w, node, legs = heapq.heappop(pq)
                if w > dist.get((node, legs), float("inf")):
                    continue

                if node in to_codes and legs > 0:
                    dst = to_info[node]
                    path = self._rebuild(parent, (node, legs))
                    walk_to = dst["distance_m"] / WALK_SPEED_M_PER_MIN
                    train_dur = sum(e[2] for e in path)
                    transfers = max(0, len(path) - 1)
                    total_dur = walk_from + train_dur + transfers * TRANSFER_PENALTY_MIN + walk_to
                    total_price = sum(e[3] for e in path)
                    candidates.append({
                        "key": total_dur if use_time else total_price,
                        "src": src, "dst": dst, "path": path,
                        "walk_from": walk_from, "walk_to": walk_to,
                        "total_duration_min": round(total_dur),
                        "total_price_rub": round(total_price, 2),
                        "transfers": transfers,
                    })

                if legs >= MAX_TRAIN_LEGS:
                    continue

                penalty = TRANSFER_PENALTY_MIN if (legs > 0 and use_time) else 0
                for nb, dur, price in self.edges.get(node, []):
                    ew = (dur + penalty) if use_time else price
                    nw = w + ew
                    ns = (nb, legs + 1)
                    if nw < dist.get(ns, float("inf")):
                        dist[ns] = nw
                        parent[ns] = (node, legs, dur, price)
                        heapq.heappush(pq, (nw, nb, legs + 1))

        candidates.sort(key=lambda c: c["key"])
        seen: set[tuple] = set()
        results: list[dict] = []
        for c in candidates:
            sig = (c["src"]["uic_code"],
                   tuple((e[0], e[1]) for e in c["path"]),
                   c["dst"]["uic_code"])
            if sig in seen:
                continue
            seen.add(sig)
            results.append(self._format(c, len(results) + 1, from_point, to_point))
            if len(results) >= max_routes:
                break
        return results

    def _rebuild(self, parent, state):
        edges = []
        cur = state
        while cur in parent:
            prev_code, prev_legs, dur, price = parent[cur]
            edges.append((prev_code, cur[0], dur, price))
            cur = (prev_code, prev_legs)
        edges.reverse()
        return edges

    def _format(self, c: dict, rid: int, from_point=None, to_point=None) -> dict:
        legs: list[dict] = []

        src = c["src"]
        walk_min = round(c["walk_from"])
        legs.append({
            "type": "walk",
            "from_name": "Точка А",
            "to_name": src["name"],
            "to_code": src["uic_code"],
            "duration_min": walk_min,
            "price_rub": 0,
            "distance_m": src["distance_m"],
            "from_lat": from_point["lat"] if from_point else src["lat"],
            "from_lon": from_point["lon"] if from_point else src["lon"],
            "to_lat": src["lat"],
            "to_lon": src["lon"],
        })

        for i, (fc, tc, dur, price) in enumerate(c["path"]):
            leg: dict = {
                "type": "train",
                "from_code": fc,
                "from_name": self.stations[fc]["name"],
                "to_code": tc,
                "to_name": self.stations[tc]["name"],
                "duration_min": round(dur),
                "price_rub": round(price, 2),
                "from_lat": self.stations[fc]["lat"],
                "from_lon": self.stations[fc]["lon"],
                "to_lat": self.stations[tc]["lat"],
                "to_lon": self.stations[tc]["lon"],
            }
            if i > 0:
                leg["transfer_wait_min"] = TRANSFER_PENALTY_MIN
            legs.append(leg)

        dst = c["dst"]
        walk_min = round(c["walk_to"])
        legs.append({
            "type": "walk",
            "from_name": dst["name"],
            "from_code": dst["uic_code"],
            "to_name": "Точка Б",
            "duration_min": walk_min,
            "price_rub": 0,
            "distance_m": dst["distance_m"],
            "from_lat": dst["lat"],
            "from_lon": dst["lon"],
            "to_lat": to_point["lat"] if to_point else dst["lat"],
            "to_lon": to_point["lon"] if to_point else dst["lon"],
        })

        return {
            "id": rid,
            "total_duration_min": c["total_duration_min"],
            "total_price_rub": c["total_price_rub"],
            "transfers": c["transfers"],
            "legs": legs,
        }


graph = RouteGraph()


@app.on_event("startup")
async def startup():
    async with SessionLocal() as session:
        try:
            await graph.load(session)
        except Exception as exc:
            logger.warning("Graph not loaded (tables may be missing): %s", exc)


@app.post("/search")
async def search_routes(req: SearchRequest):
    if not graph.has_outgoing:
        async with SessionLocal() as session:
            await graph.load(session)
    if not graph.has_outgoing:
        raise HTTPException(503, "Граф маршрутов пуст. Загрузите данные (loader).")

    stations_from = graph.find_nearest(
        req.from_lat, req.from_lon, NEARBY_LIMIT, graph.has_outgoing)
    stations_to = graph.find_nearest(
        req.to_lat, req.to_lon, NEARBY_LIMIT, graph.has_incoming)

    if not stations_from:
        raise HTTPException(404, "Не найдены станции отправления с ж/д маршрутами")
    if not stations_to:
        raise HTTPException(404, "Не найдены станции назначения с ж/д маршрутами")

    from_pt = {"lat": req.from_lat, "lon": req.from_lon}
    to_pt = {"lat": req.to_lat, "lon": req.to_lon}
    routes = graph.search(stations_from, stations_to, req.optimize_by,
                          from_point=from_pt, to_point=to_pt)

    return {
        "from_point": {"lat": req.from_lat, "lon": req.from_lon},
        "to_point": {"lat": req.to_lat, "lon": req.to_lon},
        "nearest_from": stations_from[:3],
        "nearest_to": stations_to[:3],
        "optimize_by": req.optimize_by.value,
        "routes": routes,
    }
