import os
import re
import heapq
import logging
from datetime import date, time, datetime, timedelta
from enum import Enum
from collections import defaultdict
from math import radians, cos, sin, sqrt, atan2
from typing import NamedTuple

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

app = FastAPI(title="Путешествия — API маршрутов", version="5.0.0")

WALK_SPEED_M_PER_MIN = 5000 / 60
TAXI_SPEED_M_PER_MIN = 30000 / 60
DEFAULT_MIN_TRANSFER_MIN = 15
MAX_TRAIN_LEGS = 3
NEARBY_LIMIT = 10
MAX_WALK_M = 3000
MAX_NEAREST_FALLBACK_M = 100_000
MAX_DAYS_AHEAD = 2
MINUTES_PER_DAY = 1440


def access_time_min(distance_m: float) -> float:
    """Walking up to MAX_WALK_M, taxi/transfer afterwards."""
    if distance_m <= MAX_WALK_M:
        return distance_m / WALK_SPEED_M_PER_MIN
    return distance_m / TAXI_SPEED_M_PER_MIN


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
    departure_date: date | None = None
    departure_time: time | None = None
    min_transfer_min: int = DEFAULT_MIN_TRANSFER_MIN


class TrainEdge(NamedTuple):
    to_code: str
    train_no: str
    departure_time: time
    arrival_time: time
    ride_min: float
    price_rub: float
    regularity_type: str
    regularity_desc: str


def _parse_dates_from_desc(desc: str) -> list[tuple[int, int]]:
    return [(int(m.group(1)), int(m.group(2)))
            for m in re.finditer(r"(\d{1,2})\.(\d{1,2})", desc)]


def _parse_until_date(desc: str, year: int) -> date | None:
    m = re.search(r"по\s+(\d{1,2})\.(\d{1,2})", desc)
    if m:
        try:
            return date(year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def is_running_on(d: date, regularity_type: str, regularity_desc: str) -> bool:
    rt = regularity_type.strip()

    if rt == "EveryDay":
        return True

    if rt == "Even":
        return d.day % 2 == 0

    if rt == "Odd":
        return d.day % 2 == 1

    if rt == "Days":
        until = _parse_until_date(regularity_desc, d.year)
        if until and "еж" in regularity_desc.lower():
            return d <= until

        parsed = _parse_dates_from_desc(regularity_desc)
        if not parsed:
            return True
        return (d.day, d.month) in parsed

    if rt == "DaysOfWeek":
        desc_lower = regularity_desc.lower()
        if "ежедневно" in desc_lower:
            return True
        weekday_map = {
            "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6,
        }
        for abbr, wd in weekday_map.items():
            if abbr in desc_lower and d.weekday() == wd:
                return True
        return not any(abbr in desc_lower for abbr in weekday_map)

    return True


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _minutes_to_hhmm(m: int) -> str:
    """Format absolute minutes (from query date 00:00) as 'HH:MM (+1д)' if day overflow."""
    day_offset = m // MINUTES_PER_DAY
    rem = m % MINUTES_PER_DAY
    hh, mm = divmod(rem, 60)
    base = f"{hh:02d}:{mm:02d}"
    if day_offset > 0:
        return f"{base} (+{day_offset}д)"
    return base


class RouteGraph:
    """Directed multigraph of train connections with optional time-dependent routing."""

    def __init__(self):
        self.edges: dict[str, list[TrainEdge]] = defaultdict(list)
        self.stations: dict[str, dict] = {}
        self.has_outgoing: set[str] = set()
        self.has_incoming: set[str] = set()
        self._has_schedules = False

    async def load(self, session):
        self.edges.clear()
        self.stations.clear()
        self.has_outgoing.clear()
        self.has_incoming.clear()
        self._has_schedules = False

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

        n = 0
        has_schedules = await session.execute(
            text("SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                 "WHERE table_name = 'train_schedules')")
        )
        if has_schedules.scalar():
            sched_rows = await session.execute(
                text("SELECT from_code, to_code, train_no, "
                     "departure_time, arrival_time, ride_min, "
                     "regularity_type, regularity_desc, avg_price "
                     "FROM train_schedules")
            )
            for r in sched_rows.mappings():
                fc, tc = r["from_code"], r["to_code"]
                if fc in self.stations and tc in self.stations:
                    dep_t = r["departure_time"]
                    arr_t = r["arrival_time"]
                    if isinstance(dep_t, datetime):
                        dep_t = dep_t.time()
                    if isinstance(arr_t, datetime):
                        arr_t = arr_t.time()
                    edge = TrainEdge(
                        to_code=tc,
                        train_no=r["train_no"],
                        departure_time=dep_t,
                        arrival_time=arr_t,
                        ride_min=float(r["ride_min"]),
                        price_rub=float(r["avg_price"]),
                        regularity_type=r["regularity_type"],
                        regularity_desc=r["regularity_desc"] or "",
                    )
                    self.edges[fc].append(edge)
                    self.has_outgoing.add(fc)
                    self.has_incoming.add(tc)
                    n += 1
            if n > 0:
                self._has_schedules = True

        if not self._has_schedules:
            dir_rows = await session.execute(
                text("SELECT from_code, to_code, duration_min, price_rub "
                     "FROM train_directions")
            )
            for r in dir_rows.mappings():
                fc, tc = r["from_code"], r["to_code"]
                if fc in self.stations and tc in self.stations:
                    edge = TrainEdge(
                        to_code=tc,
                        train_no="",
                        departure_time=time(0, 0),
                        arrival_time=time(0, 0),
                        ride_min=float(r["duration_min"]),
                        price_rub=float(r["price_rub"]),
                        regularity_type="EveryDay",
                        regularity_desc="ежедневно",
                    )
                    self.edges[fc].append(edge)
                    self.has_outgoing.add(fc)
                    self.has_incoming.add(tc)
                    n += 1

        logger.info("RouteGraph: %d stations, %d edges (schedules=%s), %d src, %d dst",
                     len(self.stations), n, self._has_schedules,
                     len(self.has_outgoing), len(self.has_incoming))

    def find_nearest(self, lat: float, lon: float, limit: int,
                     codes_filter: set[str] | None = None,
                     max_dist_m: float = MAX_WALK_M,
                     fallback_max_m: float = MAX_NEAREST_FALLBACK_M) -> list[dict]:
        buf = []
        for code, info in self.stations.items():
            if codes_filter is not None and code not in codes_filter:
                continue
            dlat = info["lat"] - lat
            dlon = info["lon"] - lon
            buf.append((dlat * dlat + dlon * dlon, code))
        buf.sort()
        out = []
        for _, code in buf[:limit * 4]:
            info = self.stations[code]
            dist = round(haversine_m(lat, lon, info["lat"], info["lon"]))
            out.append({
                "uic_code": code,
                "name": info["name"],
                "lat": info["lat"],
                "lon": info["lon"],
                "distance_m": dist,
            })

        within_walk = [s for s in out if s["distance_m"] <= max_dist_m]
        if len(within_walk) >= limit:
            return within_walk[:limit]

        extra = [s for s in out
                 if max_dist_m < s["distance_m"] <= fallback_max_m]
        combined = within_walk + extra[:limit - len(within_walk)]
        if combined:
            return combined

        return out[:1]

    # ------------------------------------------------------------------
    # Two search modes
    # ------------------------------------------------------------------

    def search(self, from_stations: list[dict], to_stations: list[dict],
               optimize_by: OptimizeBy, max_routes: int = 10,
               from_point: dict | None = None, to_point: dict | None = None,
               departure_date: date | None = None,
               departure_time: time | None = None,
               min_transfer_min: int = DEFAULT_MIN_TRANSFER_MIN) -> list[dict]:
        if departure_date is not None and departure_time is not None:
            return self._search_scheduled(
                from_stations, to_stations, optimize_by, max_routes,
                from_point, to_point,
                departure_date, departure_time, min_transfer_min,
            )
        return self._search_static(
            from_stations, to_stations, optimize_by, max_routes,
            from_point, to_point, departure_date,
        )

    # ------------------------------------------------------------------
    # Static mode (no time, just date filter or no filter at all)
    # ------------------------------------------------------------------

    def _edges_static(self, node: str, departure_date: date | None) -> list[TrainEdge]:
        all_edges = self.edges.get(node, [])
        if departure_date is None:
            return all_edges
        return [e for e in all_edges
                if is_running_on(departure_date, e.regularity_type, e.regularity_desc)]

    def _search_static(self, from_stations, to_stations, optimize_by, max_routes,
                       from_point, to_point, departure_date):
        to_codes = {s["uic_code"] for s in to_stations}
        to_info = {s["uic_code"]: s for s in to_stations}
        use_time = (optimize_by == OptimizeBy.time)
        candidates: list[dict] = []

        for src in from_stations:
            src_code = src["uic_code"]
            walk_from = access_time_min(src["distance_m"])

            dist: dict[tuple[str, int], float] = {}
            parent: dict[tuple[str, int], tuple[str, int, TrainEdge]] = {}

            init_w = walk_from if use_time else 0.0
            dist[(src_code, 0)] = init_w
            pq: list[tuple[float, str, int]] = [(init_w, src_code, 0)]

            while pq:
                w, node, legs = heapq.heappop(pq)
                if w > dist.get((node, legs), float("inf")):
                    continue

                if node in to_codes and legs > 0:
                    dst = to_info[node]
                    path = self._rebuild_static(parent, (node, legs))
                    walk_to = access_time_min(dst["distance_m"])
                    train_dur = sum(e.ride_min for e in path)
                    transfers = max(0, len(path) - 1)
                    total_dur = walk_from + train_dur + transfers * DEFAULT_MIN_TRANSFER_MIN + walk_to
                    total_price = sum(e.price_rub for e in path)
                    candidates.append({
                        "key": total_dur if use_time else total_price,
                        "src": src, "dst": dst, "path": path,
                        "walk_from": walk_from, "walk_to": walk_to,
                        "total_duration_min": round(total_dur),
                        "total_price_rub": round(total_price, 2),
                        "transfers": transfers,
                        "scheduled": False,
                    })

                if legs >= MAX_TRAIN_LEGS:
                    continue

                penalty = DEFAULT_MIN_TRANSFER_MIN if (legs > 0 and use_time) else 0
                for edge in self._edges_static(node, departure_date):
                    ew = (edge.ride_min + penalty) if use_time else edge.price_rub
                    nw = w + ew
                    ns = (edge.to_code, legs + 1)
                    if nw < dist.get(ns, float("inf")):
                        dist[ns] = nw
                        parent[ns] = (node, legs, edge)
                        heapq.heappush(pq, (nw, edge.to_code, legs + 1))

        return self._top_k(candidates, max_routes, from_point, to_point)

    def _rebuild_static(self, parent, state) -> list[TrainEdge]:
        edges: list[TrainEdge] = []
        cur = state
        while cur in parent:
            prev_code, prev_legs, edge = parent[cur]
            edges.append(edge)
            cur = (prev_code, prev_legs)
        edges.reverse()
        return edges

    # ------------------------------------------------------------------
    # Scheduled mode: time-dependent Dijkstra
    # ------------------------------------------------------------------

    def _next_boarding(self, edge: TrainEdge, after_min: int,
                       query_date: date) -> int | None:
        """Earliest absolute departure (minutes from query_date 00:00)
        such that boarding >= after_min and the train runs that day."""
        edge_dep_today = _time_to_minutes(edge.departure_time)
        start_day = max(0, int(after_min) // MINUTES_PER_DAY)

        for day_offset in range(start_day, start_day + MAX_DAYS_AHEAD + 1):
            check_date = query_date + timedelta(days=day_offset)
            if not is_running_on(check_date, edge.regularity_type, edge.regularity_desc):
                continue
            cand = day_offset * MINUTES_PER_DAY + edge_dep_today
            if cand >= after_min:
                return cand
        return None

    def _search_scheduled(self, from_stations, to_stations, optimize_by, max_routes,
                          from_point, to_point,
                          query_date: date, query_time: time, min_transfer_min: int):
        to_codes = {s["uic_code"] for s in to_stations}
        to_info = {s["uic_code"]: s for s in to_stations}
        use_time = (optimize_by == OptimizeBy.time)
        candidates: list[dict] = []
        query_min = _time_to_minutes(query_time)

        for src in from_stations:
            src_code = src["uic_code"]
            walk_from = access_time_min(src["distance_m"])
            start_arrival = query_min + walk_from

            init_state = (src_code, 0)
            best_key: dict[tuple[str, int], float] = {init_state: 0.0 if not use_time else start_arrival}
            arrival_at: dict[tuple[str, int], float] = {init_state: start_arrival}
            price_at: dict[tuple[str, int], float] = {init_state: 0.0}
            parent: dict[tuple[str, int],
                         tuple[str, int, TrainEdge, int, int]] = {}

            init_priority = start_arrival if use_time else 0.0
            pq: list[tuple[float, float, str, int]] = [
                (init_priority, start_arrival, src_code, 0),
            ]

            while pq:
                key, arr_here, node, legs = heapq.heappop(pq)
                if key > best_key.get((node, legs), float("inf")):
                    continue

                if node in to_codes and legs > 0:
                    dst = to_info[node]
                    walk_to = access_time_min(dst["distance_m"])
                    final_arrival = arr_here + walk_to
                    total_price = price_at[(node, legs)]
                    path = self._rebuild_scheduled(parent, (node, legs))
                    transfers = max(0, len(path) - 1)
                    total_dur = final_arrival - query_min
                    candidates.append({
                        "key": final_arrival if use_time else total_price,
                        "src": src, "dst": dst, "path": path,
                        "walk_from": walk_from, "walk_to": walk_to,
                        "total_duration_min": round(total_dur),
                        "total_price_rub": round(total_price, 2),
                        "transfers": transfers,
                        "scheduled": True,
                        "start_min": query_min,
                        "final_arrival_min": round(final_arrival),
                    })

                if legs >= MAX_TRAIN_LEGS:
                    continue

                wait_required = min_transfer_min if legs > 0 else 0
                ready_min = arr_here + wait_required

                for edge in self.edges.get(node, []):
                    boarding = self._next_boarding(edge, ready_min, query_date)
                    if boarding is None:
                        continue
                    new_arrival = boarding + edge.ride_min
                    new_price = price_at[(node, legs)] + edge.price_rub
                    new_state = (edge.to_code, legs + 1)
                    new_key = new_arrival if use_time else new_price

                    if new_key < best_key.get(new_state, float("inf")):
                        best_key[new_state] = new_key
                        arrival_at[new_state] = new_arrival
                        price_at[new_state] = new_price
                        parent[new_state] = (node, legs, edge,
                                             int(boarding), int(new_arrival))
                        heapq.heappush(pq, (new_key, new_arrival,
                                            edge.to_code, legs + 1))

        return self._top_k(candidates, max_routes, from_point, to_point)

    def _rebuild_scheduled(self, parent, state):
        path = []
        cur = state
        while cur in parent:
            prev_code, prev_legs, edge, boarding, arr = parent[cur]
            path.append((edge, boarding, arr))
            cur = (prev_code, prev_legs)
        path.reverse()
        return path

    # ------------------------------------------------------------------
    # Output formatting
    # ------------------------------------------------------------------

    def _top_k(self, candidates, max_routes, from_point, to_point):
        candidates.sort(key=lambda c: c["key"])
        seen: set[tuple] = set()
        results: list[dict] = []
        for c in candidates:
            path = c["path"]
            if c.get("scheduled"):
                sig = (c["src"]["uic_code"],
                       tuple((p[0].to_code, p[0].train_no, p[1]) for p in path),
                       c["dst"]["uic_code"])
            else:
                sig = (c["src"]["uic_code"],
                       tuple((e.to_code, e.train_no) for e in path),
                       c["dst"]["uic_code"])
            if sig in seen:
                continue
            seen.add(sig)
            results.append(self._format(c, len(results) + 1, from_point, to_point))
            if len(results) >= max_routes:
                break
        return results

    def _format(self, c: dict, rid: int, from_point=None, to_point=None) -> dict:
        legs: list[dict] = []
        src = c["src"]
        scheduled = c.get("scheduled", False)

        walk_from_min = round(c["walk_from"])
        legs.append({
            "type": "walk",
            "mode": "walk" if src["distance_m"] <= MAX_WALK_M else "taxi",
            "from_name": "Точка А",
            "to_name": src["name"],
            "to_code": src["uic_code"],
            "duration_min": walk_from_min,
            "price_rub": 0,
            "distance_m": src["distance_m"],
            "from_lat": from_point["lat"] if from_point else src["lat"],
            "from_lon": from_point["lon"] if from_point else src["lon"],
            "to_lat": src["lat"],
            "to_lon": src["lon"],
        })

        if scheduled:
            self._format_scheduled_legs(c, src, legs)
        else:
            self._format_static_legs(c, src, legs)

        dst = c["dst"]
        legs.append({
            "type": "walk",
            "mode": "walk" if dst["distance_m"] <= MAX_WALK_M else "taxi",
            "from_name": dst["name"],
            "from_code": dst["uic_code"],
            "to_name": "Точка Б",
            "duration_min": round(c["walk_to"]),
            "price_rub": 0,
            "distance_m": dst["distance_m"],
            "from_lat": dst["lat"],
            "from_lon": dst["lon"],
            "to_lat": to_point["lat"] if to_point else dst["lat"],
            "to_lon": to_point["lon"] if to_point else dst["lon"],
        })

        out = {
            "id": rid,
            "total_duration_min": c["total_duration_min"],
            "total_price_rub": c["total_price_rub"],
            "transfers": c["transfers"],
            "legs": legs,
            "scheduled": scheduled,
        }
        if scheduled:
            out["start_min"] = c["start_min"]
            out["final_arrival_min"] = c["final_arrival_min"]
        return out

    def _format_static_legs(self, c, src, legs):
        path: list[TrainEdge] = c["path"]
        for i, edge in enumerate(path):
            fc = path[i - 1].to_code if i > 0 else src["uic_code"]
            leg = self._train_leg_base(edge, fc)
            if i > 0:
                leg["transfer_wait_min"] = DEFAULT_MIN_TRANSFER_MIN
            legs.append(leg)

    def _format_scheduled_legs(self, c, src, legs):
        path = c["path"]
        prev_arrival_min = c.get("start_min", 0) + round(c["walk_from"])
        for i, (edge, boarding, arrival) in enumerate(path):
            fc = path[i - 1][0].to_code if i > 0 else src["uic_code"]
            leg = self._train_leg_base(edge, fc)
            leg["boarding_min"] = boarding
            leg["arrival_min"] = arrival
            leg["boarding_label"] = _minutes_to_hhmm(boarding)
            leg["arrival_label"] = _minutes_to_hhmm(arrival)
            wait = max(0, boarding - prev_arrival_min)
            if i == 0:
                leg["initial_wait_min"] = wait
            else:
                leg["transfer_wait_min"] = wait
            legs.append(leg)
            prev_arrival_min = arrival

    def _train_leg_base(self, edge: TrainEdge, fc: str) -> dict:
        return {
            "type": "train",
            "train_no": edge.train_no,
            "departure_time": (edge.departure_time.strftime("%H:%M")
                               if edge.departure_time != time(0, 0) else None),
            "arrival_time": (edge.arrival_time.strftime("%H:%M")
                             if edge.arrival_time != time(0, 0) else None),
            "regularity_desc": edge.regularity_desc or None,
            "from_code": fc,
            "from_name": self.stations[fc]["name"],
            "to_code": edge.to_code,
            "to_name": self.stations[edge.to_code]["name"],
            "duration_min": round(edge.ride_min),
            "price_rub": round(edge.price_rub, 2),
            "from_lat": self.stations[fc]["lat"],
            "from_lon": self.stations[fc]["lon"],
            "to_lat": self.stations[edge.to_code]["lat"],
            "to_lon": self.stations[edge.to_code]["lon"],
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
    routes = graph.search(
        stations_from, stations_to, req.optimize_by,
        from_point=from_pt, to_point=to_pt,
        departure_date=req.departure_date,
        departure_time=req.departure_time,
        min_transfer_min=req.min_transfer_min,
    )

    return {
        "from_point": {"lat": req.from_lat, "lon": req.from_lon},
        "to_point": {"lat": req.to_lat, "lon": req.to_lon},
        "nearest_from": stations_from[:3],
        "nearest_to": stations_to[:3],
        "optimize_by": req.optimize_by.value,
        "departure_date": req.departure_date.isoformat() if req.departure_date else None,
        "departure_time": req.departure_time.strftime("%H:%M") if req.departure_time else None,
        "min_transfer_min": req.min_transfer_min,
        "routes": routes,
    }


@app.post("/reload")
async def reload_graph():
    async with SessionLocal() as session:
        await graph.load(session)
    return {
        "status": "ok",
        "stations": len(graph.stations),
        "sources": len(graph.has_outgoing),
        "destinations": len(graph.has_incoming),
        "has_schedules": graph._has_schedules,
    }
