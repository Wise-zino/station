<div align="center">

# Station

**A fast Django REST API that plans the cheapest fuel stops for any road trip across the USA.**

Give it a start and a finish. Get back the driving route, the most cost-effective places to fuel up
along the way (500-mile range), and the total fuel bill at 10 MPG.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2-092E20?logo=django&logoColor=white)
![DRF](https://img.shields.io/badge/DRF-3.15%2B-A30000)
![NumPy](https://img.shields.io/badge/NumPy-vectorized-013243?logo=numpy&logoColor=white)
![SciPy](https://img.shields.io/badge/SciPy-KD--tree-8CAAE6?logo=scipy&logoColor=white)
![Tests](https://img.shields.io/badge/tests-51%20passing-brightgreen)

<img width="500" height="500" alt="station API demo screenshot" src="https://github.com/user-attachments/assets/25f49557-c305-4b93-b3b2-821d9e934884" />


</div>

---

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [API reference](#api-reference)
- [Design decisions and assumptions](#design-decisions-and-assumptions)
- [Performance](#performance)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Limitations and future work](#limitations-and-future-work)

## Features

- **Cost-optimal fuel stops.** Chooses where to fill up, and how much to buy at each stop, to minimise
  total spend for a vehicle with a 500-mile range.
- **Total fuel cost.** Assumes 10 miles per gallon; every gallon burned is paid for at the price of the
  station it was bought from.
- **Fast by design.** One call to the map/routing API (two or three at most for free-text input, zero for
  repeated routes). All station matching and optimisation runs in memory in a few milliseconds.
- **Flexible input.** Locations can be free text (`"Chicago, IL"`) or coordinates (`"41.88,-87.63"`).
- **Interactive map.** A Leaflet map page draws the route and numbered fuel stops from the same result.
- **Self-documenting.** Swagger UI and an OpenAPI schema are generated from the code.
- **Predictable errors.** Every failure returns the same JSON shape with a meaningful HTTP status.

## How it works

```mermaid
flowchart LR
    A[Client] -->|POST or GET /api/route/| B[DRF view]
    B --> C[Resolve locations<br/>coordinates or geocode]
    C --> D[Routing provider<br/>one call, cached]
    D --> E[Corridor matching<br/>NumPy + SciPy KD-tree]
    E --> F[Fuel optimizer]
    F --> G[JSON + GeoJSON<br/>and /map/ page]
```

1. **Resolve** the start and finish. Coordinates need no API call; free text is geocoded and cached.
2. **Route** with a single directions request returning the full road geometry. The result is cached, so a
   repeated trip makes no external calls at all.
3. **Match** fuel stations to the route. Mile markers are computed along the geometry, then a KD-tree finds
   every station within 10 miles of the road and the mile at which it sits.
4. **Optimise** the stops with a greedy rule that is provably optimal for this problem (see below).
5. **Respond** with the route, stops, totals and a link to the interactive map.

### Station data

The provided fuel price file (`data/fuel-prices.csv`) has 8,151 rows and no coordinates. It is cleaned and
geocoded once, offline, so requests never wait on a geocoder:

| Step | Result |
|---|---|
| Rows in file | 8,151 |
| Non-US rows removed (Canadian provinces) | 620 |
| Repeated OPIS truckstop IDs merged (prices averaged) | 905 rows |
| **Unique US stations** | **6,626** |
| Geocoded by city and state (Nominatim), cached in `data/geocode_cache.json` | all but 33 stations |

## Tech stack

| Layer | Technology | Used for |
|---|---|---|
| Web framework | **Django 5.2**, **Django REST Framework** | API views, validation, error handling |
| API docs | **drf-spectacular** | OpenAPI schema and Swagger UI |
| Numerics | **NumPy** | Vectorised haversine distances and cumulative mile markers over tens of thousands of route vertices, in-memory station arrays, bounding-box prefiltering, Douglas-Peucker route simplification |
| Spatial search | **SciPy** (`cKDTree`) | One batched nearest-neighbour query that maps every candidate station to its closest point on the route, using 3D sphere coordinates so "within N miles" is correct at any latitude |
| Routing | **OSRM** public server (default) or **OpenRouteService** | Driving directions with full geometry |
| Geocoding | **Nominatim** (OpenStreetMap) | Free-text locations (cached) and the one-time station geocode |
| Map | **Leaflet** + OpenStreetMap tiles | Interactive route and stop display |
| Storage | SQLite, Django local-memory cache | Station table, route and geocode caches |

### Why NumPy and SciPy

The hot path works with a lot of numbers: a cross-country route has 50,000+ vertices, and the station table
holds 6,600+ points. Plain Python loops over that would dominate the response time, so:

- **NumPy** turns the distance and mile-marker math into array operations. Computing mile markers for a
  60,000-vertex route takes about 5 ms.
- **SciPy's KD-tree** replaces a stations-times-vertices distance comparison with a single indexed query
  (multi-threaded with `workers=-1`). Matching 6,600 stations to a 60,000-vertex route takes about 24 ms.

## Getting started

### Prerequisites

- Python 3.10 or newer
- Internet access for routing and geocoding calls

### Installation

```bash
git clone github.com/Wise-zino/station station && cd station
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py load_stations                         # clean the CSV into the database
python manage.py geocode_stations --apply-only         # apply the bundled geocode cache (no network)

python manage.py runserver
```

Then open:

| URL | What |
|---|---|
| http://127.0.0.1:8000/api/docs/ | Swagger UI (also served at `/`) |
| http://127.0.0.1:8000/map/?start=New+York,+NY&finish=Los+Angeles,+CA | Interactive map |

> The geocode cache is committed, so setup takes seconds. To rebuild it from scratch run
> `python manage.py geocode_stations` (about an hour; it is resumable and respects Nominatim's rate limit).
> Before doing so, set `GEOCODER_USER_AGENT` in `config/settings.py` to your own contact details, as
> Nominatim's usage policy requires.

### Configuration

Settings live in `config/settings.py`; routing options can be set with environment variables.

| Setting | Default | Description |
|---|---|---|
| `ROUTING_PROVIDER` (env) | `osrm` | `osrm` (no key) or `ors` (OpenRouteService) |
| `ORS_API_KEY` (env) | empty | Required only when `ROUTING_PROVIDER=ors` |
| `OSRM_BASE_URL` (env) | public OSRM server | Point at a self-hosted OSRM for production |
| `VEHICLE_RANGE_MILES` | `500` | Maximum distance on a full tank |
| `VEHICLE_MPG` | `10` | Fuel economy |
| `CORRIDOR_MILES` | `10` | How far from the route a station may be and still be considered |
| `ROUTE_CACHE_SECONDS` | 86,400 | How long a computed route is cached |
| `MAP_TILE_URL` | OpenStreetMap | Swap in another tile provider if needed |

## API reference

Interactive documentation is available at `/api/docs/`. The OpenAPI schema is at `/api/schema/`.

### `POST /api/route/`

```bash
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "New York, NY", "finish": "Los Angeles, CA"}'
```

`GET /api/route/?start=...&finish=...` returns the same result.

**Response** (abridged; values are illustrative):

```json
{
  "start":  { "query": "New York, NY", "label": "New York, USA", "lat": 40.7128, "lon": -74.006 },
  "finish": { "query": "Los Angeles, CA", "label": "Los Angeles, USA", "lat": 34.0522, "lon": -118.2437 },
  "route": {
    "distance_miles": 2790.4,
    "duration_hours": 41.2,
    "geometry": { "type": "LineString", "coordinates": [[-74.006, 40.7128], "..."] }
  },
  "fuel_stops": [
    { "order": 1, "kind": "origin",  "name": "Departure fill-up (at origin)", "route_mile": 0.0,
      "price_per_gallon": 3.412, "gallons": 18.4, "cost": 62.78, "lat": 40.7128, "lon": -74.006 },
    { "order": 2, "kind": "station", "name": "Example Travel Center", "city": "Example", "state": "PA",
      "route_mile": 184.0, "miles_off_route": 1.3, "price_per_gallon": 3.189,
      "gallons": 50.0, "cost": 159.45, "lat": 40.0, "lon": -78.0 }
  ],
  "summary": {
    "total_fuel_cost": 904.12, "total_gallons": 279.04, "stops_count": 7,
    "vehicle_range_miles": 500, "mpg": 10.0,
    "departure_price_per_gallon": 3.412, "departure_price_source": "nearest station to origin (...)"
  },
  "map_url": "http://127.0.0.1:8000/map/?start=New+York%2C+NY&finish=Los+Angeles%2C+CA",
  "meta": { "external_api_calls": 3, "route_cached": false,
            "timings_ms": { "route": 410.2, "match": 24.0, "optimize": 0.2, "total": 438.9 } }
}
```

`meta` reports how many external map/routing calls the request made and where the time went, so the
call budget is visible on every response.

### Errors

All errors share one shape: `{"error": {"type": "...", "message": "..."}}`.

| Status | Meaning |
|---|---|
| `400` | Missing or invalid input, a location that cannot be found, or a location outside the USA |
| `422` | The route exists but no valid fuel plan does (for example, a stretch longer than 500 miles with no station) |
| `502` | The routing provider failed or timed out |

## Design decisions and assumptions

**Optimiser.** The problem is the classic gas-station problem. From each stop the algorithm looks at every
station reachable on a full tank: if a cheaper one exists it drives to the nearest cheaper one and buys only
enough fuel to get there; otherwise it fills the tank and drives to the cheapest reachable station. The
destination is treated as a station priced at zero so the final stop buys only what is needed.

**Starting fuel.** The tank starts empty and the origin behaves like a station priced at the nearest
station to the start. This means every gallon burned is paid for: a 300-mile trip has a real cost rather
than showing zero. The departure fill-up appears as the first entry in `fuel_stops` (`kind: "origin"`).

**Station location precision.** The source file contains highway-exit style addresses that geocoders cannot
resolve reliably, so stations are placed at their city's coordinates. The 10-mile corridor absorbs this
imprecision, and each stop reports `miles_off_route`.

**Duplicate prices.** Several OPIS rows share a station ID with different prices. They are merged into one
station using the mean price (configurable with `load_stations --price-strategy min|mean|median`).

**Route geometry.** Station matching uses the full-resolution geometry for accuracy. The geometry returned
to clients is a Douglas-Peucker simplification (0.1 mile tolerance), computed once per route and cached,
which keeps responses a few KB instead of megabytes.

**External call budget.** Coordinates cost one call (directions). Free text costs three on a cold cache
(two geocodes plus directions). Geocodes and routes are cached, so repeats cost none.

## Performance

Measured on synthetic data shaped like the real workload (3,700-mile route, 60,000 vertices, 6,600 stations):

| Stage | Time |
|---|---|
| Mile markers for the whole route (NumPy) | about 5 ms |
| Match stations to the route (SciPy KD-tree) | about 24 ms |
| Optimise fuel stops | about 0.2 ms |
| Simplify display geometry (once per route, then cached) | about 55 ms |

With the routing response cached, a request is served in single-digit milliseconds. A cold request is
dominated by the one directions call to the routing provider.

## Testing

```bash
python manage.py test
```


The suite has 51 tests covering:

- **Data cleaning and loading:** Canadian rows dropped, duplicates merged, idempotent re-loads that keep
  existing coordinates.
- **Routing:** coordinate parsing, geocode and route caching, and the external-call budget (1 call for
  coordinates, 3 for free text, 0 for repeats), provider errors and timeouts.
- **Optimiser:** results compared against an exhaustive dynamic-programming search on 250 random
  instances (the cost matched every time), plus checks that the tank never overflows or runs dry.
- **Corridor matching:** stations inside and outside the corridor, mile-marker accuracy.
- **API and map:** response shape, validation, error status codes, OpenAPI schema generation, safe
  rendering of station names, and the Referrer-Policy header OpenStreetMap tiles require.

External services are mocked in tests, so the suite runs offline and in about a second.

## Project structure

```
station/
├── config/            # Django settings and URL routing
├── stations/          # Station model, CSV cleaning, load_stations and geocode_stations commands
├── routing/           # Location resolution, routing providers, caching, geometry math, simplification
├── planner/           # Station index, KD-tree corridor matching, fuel optimizer, trip planning service
├── api/               # DRF endpoint, serializers, error handler, map page and Swagger wiring
├── data/              # Fuel price CSV and the geocode cache
```

Two management commands are handy for debugging: `python manage.py route_debug "Chicago, IL" "Dallas, TX"`
prints routing latency and call counts, and `python manage.py plan_debug "New York, NY" "Los Angeles, CA"`
prints the full plan and timings from the command line.

## Limitations and future work

- **Detours are not priced.** A station a few miles off the route counts as if it were on it. Adding the
  detour distance to each station's effective price would be the next refinement.
- **City-level station coordinates.** Geocoding exact exit addresses would tighten placement.
- **Public routing server.** The default OSRM demo server is fine for an assessment; production should use a
  self-hosted OSRM or a keyed provider.
- **Per-process cache.** The default local-memory cache is not shared between workers; use Redis when
  running several.
- **Stop count.** The strict optimum can chain several stations with tiny price differences. A minimum
  savings threshold would trade a few cents for fewer stops.
- **Vehicle model.** Range and MPG are fixed settings; making them request parameters is a small extension.
