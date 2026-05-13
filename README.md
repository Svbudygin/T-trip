# T-Travel — rail route planner

Web application for finding rail routes between two map coordinates over the RZD network.

> **Deploying on a new server:** see [DEPLOYMENT.md](DEPLOYMENT.md) for step-by-step instructions when you receive a database dump.

The user sets points **A** and **B** (coordinates or map clicks), optionally a departure date and time (MSK), and the system returns up to **10** ranked routes optimized by **time** or **cost**.

Production: **https://trip.svbudygin.ru**

---

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│   Streamlit  │────>│   FastAPI    │────>│  PostgreSQL +    │
│   (frontend) │<────│   (backend)  │<────│  PostGIS (db)    │
│   :8501      │     │   :8000      │     │  :5432           │
└──────────────┘     └──────────────┘     └──────────────────┘
                                                   ^
                                                   |
                                          ┌────────┴────────┐
                                          │  loader (one-off)│
                                          │  schedule-loader │
                                          └─────────────────┘
```

All services run via **Docker Compose**.

---

## Project layout

```
t_trip/
├── backend/                 # FastAPI backend
│   ├── main.py              # POST /search, POST /reload
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                # Streamlit UI
│   └── app.py
├── scripts/
│   ├── load_train_directions.py   # Stations + aggregated directions
│   ├── load_train_schedules.py    # Per-train timetable CSV → DB
│   ├── enrich_excel_with_coords.py
│   ├── init_train_directions.sql
│   ├── benchmark_search.py          # Latency benchmark
│   └── restore-dump.sh
├── tests/                   # pytest OD suite + oracle tests
├── data/                    # Source data (not in git)
├── docker-compose.yml
└── README.md
```

---

## Database (`train`)

### From OSM dump

| Table | Description |
|-------|-------------|
| `planet_osm_nodes` | OSM nodes with `hstore` tags (`uic_ref` for RZD stations) |
| `osm_stations` | Station geometries (map / import helper) |
| Other `planet_osm_*` | Lines, polygons, roads |

### Created by loaders

| Table | Description |
|-------|-------------|
| `rzd_stations` | `uic_code`, `name`, `lat`, `lon` (matched via OSM `uic_ref`) |
| `train_directions` | Aggregated edges: `duration_min`, `price_rub` (fallback graph) |
| `train_schedules` | Per-train rows: times, regularity, price (production graph) |

---

## How routing works

On startup the backend loads stations and edges into an **in-memory graph** and builds **R-tree** indexes for nearest-station lookup.

1. Find up to **10** connected stations near each endpoint (prefer ≤3 km, fallback up to 100 km).
2. **Multi-source Dijkstra** on an augmented product graph (max **3** train legs = 2 transfers).
3. **Access legs:** walk (≤3 km) or taxi (>3 km) from/to coordinates.
4. **Scheduled mode** (production): when `train_schedules` is loaded and the request includes `departure_date` + `departure_time`, time-dependent Dijkstra uses real boarding times and waits.
5. **Static mode:** no clock times; optional date filter on regularity; fixed **15 min** transfer allowance per transfer when optimizing by time.
6. Deduplicate, sort, return up to **10** routes.

| Parameter | Value |
|-------------|--------|
| Nearby stations (search) | 10 per endpoint |
| Nearby stations (JSON response) | 3 closest |
| Max train legs | 3 |
| Transfer penalty (static, time mode) | 15 min |
| Min transfer (scheduled) | 15 min (configurable via API) |
| Walk speed | 5 km/h |
| Taxi speed | 30 km/h (beyond 3 km) |

---

## Quick start

### 1. Start services

```bash
cd /root/t_trip
docker compose up -d --build
```

Optional dev bind-mount: `cp docker-compose.override.yml.example docker-compose.override.yml`

- **db** — PostgreSQL + PostGIS (port 5432 bound to localhost only)
- **backend** — `:8000`
- **frontend** — `:8501`

### 2. Load aggregated directions (one-off)

```bash
docker compose --profile load run --rm loader
```

### 3. Load per-train schedules (recommended for production)

```bash
docker compose --profile load-schedules run --rm schedule-loader
```

Then reload the in-memory graph (or restart backend):

```bash
curl -X POST http://localhost:8000/reload
```

### 4. Open the app

- Streamlit: **http://&lt;host&gt;:8501**
- API docs: **http://&lt;host&gt;:8000/docs**

---

## Docker commands

```bash
docker compose ps
docker compose logs -f backend
docker compose restart backend
docker compose up -d --build backend
docker compose down
```

---

## Database access (DBeaver via SSH tunnel)

Port 5432 is not exposed publicly. Use an SSH tunnel:

- SSH: server IP, port 22, your user/key
- PostgreSQL: `localhost:5432`, database `train`, user `postgres`, password from `docker-compose.yml`

---

## Restore OSM dump

```bash
chmod +x scripts/restore-dump.sh
./scripts/restore-dump.sh /path/to/train1.dump
docker compose --profile load run --rm loader
docker compose --profile load-schedules run --rm schedule-loader
```

---

## API

### `POST /search`

```json
{
  "from_lat": 55.7558,
  "from_lon": 37.6173,
  "to_lat": 59.9343,
  "to_lon": 30.3351,
  "optimize_by": "time",
  "departure_date": "2026-05-26",
  "departure_time": "07:00",
  "min_transfer_min": 15
}
```

Response includes `nearest_from`, `nearest_to`, and `routes[]` with `legs` (walk/taxi + train), `scheduled`, boarding/arrival labels when applicable.

### `POST /reload`

Rebuild graph and R-tree indexes from the database. Returns station/edge counts and `has_schedules`.

---

## Tests

Against a running backend (`API_URL`, default `http://localhost:8000`):

```bash
pip install -r tests/requirements.txt
pytest tests/ -v
```

- `tests/od_suite.yaml` — 50 integration cases
- `tests/test_routing_optimality.py` — synthetic-graph oracle checks

Benchmark:

```bash
python scripts/benchmark_search.py
```

---

## Stack

| Component | Technology |
|-----------|------------|
| Database | PostgreSQL 16 + PostGIS 3.4 |
| Backend | Python 3.12, FastAPI, SQLAlchemy (async), asyncpg, rtree |
| Frontend | Streamlit, Folium |
| Deploy | Docker Compose, Nginx + HTTPS (production) |
| Data | OSM (dump), RZD Excel + schedule CSV |
