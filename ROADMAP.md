# HA Traffic Monitor — Roadmap & Work Plan

A Home Assistant add-on that monitors drive time and traffic conditions for user-defined
routes (commutes, school runs, etc.), exposes them as entities, and provides an ingress
UI with a map for picking which of several alternative routes you actually drive.

Requirements live in [CLAUDE.md](CLAUDE.md). This document is the plan for building them.

---

## 1. Decisions

These were settled before planning; recording them here so they don't get relitigated.

| # | Decision | Rationale |
|---|---|---|
| D1 | **Traffic/routing provider: TomTom** | 20,000 requests/month free with **no credit card required**. Supports live traffic, up to 5 alternative routes per call, toll avoidance, and route reconstruction — every requirement in one API. HERE retired its no-CC Limited plan on 2025-08-31; Google Maps has no meaningful free tier. |
| D2 | **Entities via MQTT Discovery** | An add-on is a Docker container and cannot create entities directly. MQTT Discovery gives real registry-backed devices and entities that survive restarts, with no YAML for the user. Declared as `services: ["mqtt:want"]`. |
| D3 | **Backend: Python 3.12 + FastAPI** | Idiomatic for the HA ecosystem, async polling loop, and one process serves both the JSON API and the static UI. |
| D4 | **Frontend: vanilla JS + Leaflet**, no build step | Ingress serves static files. A bundler would add CI complexity for a UI this size. Leaflet + OSM tiles are free and need no key. |
| D5 | **Ship a walking skeleton first** | M0–M2 put a live sensor in Home Assistant before any UI exists. Proves the riskiest integration points early. |
| D6 | **Provider access sits behind an interface** | A `TrafficProvider` protocol with a TomTom implementation. Keeps the door open for HERE/Mapbox without committing to them now. |

### Deliberately out of scope for v1

Transit/cycling modes, historical trend storage (HA's recorder already does this), route
optimisation across multiple stops, incident detail feeds, and push notifications — the user
builds those as HA automations on top of our entities.

---

## 2. The API budget is the central design constraint

This shapes more of the architecture than anything else, so it comes first.

**Free tier: 20,000 requests/month, or roughly 666/day across all routes.**

| Polling strategy | Requests/day/route | Routes that fit in the free tier |
|---|---|---|
| Every 5 min, 24/7 | 288 | **2** |
| Every 15 min, 24/7 | 96 | 6 |
| Every 5 min, weekdays, two 3-hour windows | ~36 | **~25** |

CLAUDE.md requires "as many routes as they would like." Naive continuous polling makes that
impossible on the free tier. Therefore:

- **Active windows are a first-class feature, not an optimisation.** Each route carries a
  schedule (days of week plus time ranges). Outside its windows a route is not polled, and its
  entities hold their last value with a stale marker.
- **A hard budget guard** tracks rolling 30-day usage in `/data/usage.json`. At 80% it warns in
  the log and via a diagnostic entity; at 100% it stops polling rather than risk charges. This
  is a safety property — the user handed us a key, and we don't get to spend it freely.
- **Geocoding results are cached permanently.** Addresses don't move. One request per address,
  ever, keyed by the normalised address string.
- **One request covers all alternatives.** `maxAlternatives=5` returns the chosen route and its
  alternatives in a single billable call.

Defaults ship conservative (15 min, windowed), and the UI shows a live "projected monthly
usage" figure that updates as the user adds routes.

---

## 3. Architecture

```
┌─ Home Assistant ────────────────────────────────────────────────┐
│                                                                  │
│   Sidebar panel ──ingress──►┌──────────────────────────────┐    │
│                             │  ha-traffic-monitor add-on   │    │
│   MQTT integration ◄────────┤                              │    │
│        ▲                    │  FastAPI                     │    │
│        │                    │   ├─ /api/*   config CRUD    │    │
│        │ discovery+state    │   ├─ /        static UI      │    │
│        │                    │   └─ scheduler (asyncio)     │    │
│   ┌────┴─────┐              │         │                    │    │
│   │ Mosquitto│◄─────────────┤  publisher ──┐               │    │
│   └──────────┘              │              │               │    │
│                             │  ┌───────────▼────────────┐  │    │
│                             │  │ TrafficProvider        │  │    │
│                             │  │  └ TomTomProvider      │──┼────┼──► api.tomtom.com
│                             │  ├ budget guard           │  │    │
│                             │  └ geocode cache          │  │    │
│                             │                            │  │    │
│                             │  /data/  routes.json       │  │    │
│                             │          usage.json        │  │    │
│                             │          geocache.json     │  │    │
│                             └──────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

**Why config lives in `/data/routes.json` rather than add-on options:** add-on options are
edited as YAML in the Supervisor UI and can't express "pick this route from a map." Routes are
managed entirely in our own UI. Add-on options hold only what must exist before the UI can
start — the API key, unit system, log level, and MQTT overrides.

### Repository layout

```
HA-Traffic-Monitor/
├── repository.yaml                 # HA add-on repository manifest
├── README.md                       # install via repo URL
├── CLAUDE.md
├── ROADMAP.md
└── traffic_monitor/                # the add-on itself
    ├── config.yaml                 # slug, arch, ingress, services, options, schema
    ├── build.yaml                  # per-arch base images
    ├── Dockerfile
    ├── run.sh                      # bashio: read options -> env -> exec app
    ├── DOCS.md                     # user-facing docs (shown in the add-on tab)
    ├── CHANGELOG.md
    ├── app/
    │   ├── main.py                 # FastAPI app + lifespan
    │   ├── config.py               # options + routes.json load/save/migrate
    │   ├── models.py               # pydantic: Route, RouteResult, Schedule
    │   ├── scheduler.py            # asyncio poll loop, window logic
    │   ├── budget.py               # rolling-30d usage guard
    │   ├── mqtt.py                 # discovery + state publishing, availability
    │   ├── api.py                  # /api routers
    │   └── providers/
    │       ├── base.py             # TrafficProvider protocol
    │       └── tomtom.py
    ├── www/                        # index.html, app.js, styles.css, vendored Leaflet
    └── tests/
        ├── fixtures/               # recorded TomTom JSON responses
        └── test_*.py
```

---

## 4. Entity model

One MQTT device per route (`identifiers: ha_traffic_<route_id>`), so entities group naturally
and the user can rename them from the HA UI.

| Entity | Class / unit | Notes |
|---|---|---|
| `sensor.<route>_duration` | duration, min | Current drive time with live traffic (`travelTimeInSeconds`) |
| `sensor.<route>_duration_typical` | duration, min | `noTrafficTravelTimeInSeconds` — the absolute free-flow baseline |
| `sensor.<route>_delay` | duration, min | `duration − duration_typical`. How much longer than best-case, right now — the number most automations should key off |
| `sensor.<route>_incident_delay` | duration, min | `trafficDelayInSeconds` as TomTom defines it: delay from incidents *relative to the historic norm for this time of day*, not relative to free-flow. Usually 0; moves for accidents/closures/abnormal congestion |
| `sensor.<route>_distance` | distance, km/mi | Follows the configured unit system |
| `sensor.<route>_eta` | timestamp | Arrival time if leaving now; HA renders this as a live countdown |
| `sensor.<route>_traffic_level` | enum | `free_flow` / `light` / `moderate` / `heavy`, derived from `_delay` ÷ `_duration_typical` |
| `sensor.api_requests_remaining` | diagnostic | Budget guard; one per add-on, not per route |

**Correction from the original draft:** `trafficDelayInSeconds` was initially assumed to be
"delay vs. free-flow" and slated as the primary `_delay` sensor. Live testing against a real
route (Magnolia, TX → Spring, TX) showed it's actually delay from incidents *relative to the
historic-typical time for that hour* — it reads 0 during ordinary rush-hour congestion and only
moves for genuinely abnormal conditions. That's a real and useful signal, but not what most
users mean by "is there traffic right now," so `_delay` is now computed client-side as
`duration − duration_typical`, and the raw TomTom field ships as a separate `_incident_delay`
sensor for automations that specifically want to know about abnormal events.

Shared attributes on `_duration`: `route_name`, `origin`, `destination`, `avoid_tolls`,
`polyline` (so map cards can draw it), `last_updated`, `stale`, `in_active_window`.

Availability is published on a shared status topic with an MQTT Last Will, so entities go
`unavailable` rather than silently stale if the add-on dies.

`traffic_level` thresholds, as `_delay` over `_duration_typical`: under 5% is `free_flow`,
under 20% `light`, under 50% `moderate`, above that `heavy`.

---

## 5. Route pinning — the one genuinely hard problem

CLAUDE.md requires that the user pick from suggested routes, because "a user might not drive
the most efficient route every day." That requirement is harder than it first appears.

**The problem:** TomTom returns alternatives ranked by current conditions, with no stable
identifiers. The route that came back as alternative #2 this morning may be #1, #3, or missing
entirely this afternoon. Matching by index is wrong, and matching by summary statistics is
unreliable — either would silently swap the user's chosen route for a different road when
traffic shifts, which is exactly the failure the requirement exists to prevent.

**The solution:** pin the chosen route by its *geometry*, and re-evaluate that same geometry on
every poll.

1. When the user picks a route in the UI, keep its polyline, downsampled to roughly one point
   every 500 m and capped well under the API's supporting-points limit.
2. Every subsequent poll is a **POST** to `calculateRoute` carrying those points as
   `supportingPoints`, with `routeRepresentation=encodedPolyline`. TomTom reconstructs the same
   physical path and re-costs it against current traffic.
3. The response is therefore always *the road the user actually drives*, not whatever happens to
   be fastest right now.
4. A "re-scan alternatives" action in the UI re-runs the GET with `maxAlternatives=5`, so the
   user can deliberately re-pick — after roadworks change the options, for instance.

Verified against the TomTom docs: `supportingPoints` is documented as "input for route
reconstruction," and `maxAlternatives` accepts 0–5.

Store both the pinned geometry and the original origin/destination, so a route can always be
re-scanned from scratch.

---

## 6. Milestones

Each milestone ends in something demonstrably working. M0 through M2 form the walking skeleton.

### M0 — Add-on scaffold that installs

*Goal: it appears in Home Assistant and starts.*

- `repository.yaml`, `traffic_monitor/config.yaml`, `build.yaml`, `Dockerfile`, `run.sh`
- `config.yaml`: `ingress: true`, `ingress_port: 8099`, `panel_icon: mdi:traffic-light`,
  `services: ["mqtt:want"]`, `arch: [aarch64, amd64, armv7]`, and an options schema with
  `api_key: password`, `unit_system: list(metric|imperial)`, `log_level`
- FastAPI serving a placeholder page over ingress
- **Gotcha:** since Supervisor 2026.04.0 the `BUILD_FROM` arg is no longer injected by default.
  Use an explicit `FROM ghcr.io/home-assistant/{arch}-base-python:...` driven by `build.yaml`.

**Done when:** the add-on installs from a local repo, starts, and its panel opens in the sidebar.

### M1 — Routing core

*Goal: a tested library that answers "how long is this drive right now?"*

- `models.py`, `providers/base.py`, `providers/tomtom.py`
- Geocoding via the TomTom Search API, with a permanent `/data/geocache.json`
- `calculate_route()` — GET with `traffic=true`, `computeTravelTimeFor=all`,
  `maxAlternatives=5`, and `avoid=tollRoads` when the route opts out of tolls
- `budget.py`: rolling 30-day counter with 80% warn and 100% stop
- Error handling: 403 bad key, 429 rate limit (5 req/s — serialise behind a semaphore), network
  timeouts retried with backoff. The poll loop must never die.
- Unit tests against **recorded fixtures**, so the suite never spends API quota

**Done when:** `pytest` passes offline, and a manual smoke script prints live duration and delay
for a real address pair.

### M2 — Walking skeleton: one live sensor

*Goal: a real number, updating, in Home Assistant.*

- `mqtt.py`: connect using credentials from the `mqtt:want` service (with manual override),
  publish retained discovery configs, set up the availability topic and LWT
- `scheduler.py`: minimal fixed-interval async loop
- One hardcoded route from add-on options, wired end to end

**Done when:** `sensor.*_duration` exists in HA, updates on schedule, and survives an HA restart.
**This is the highest-value checkpoint in the plan** — every integration risk is retired here.

### M3 — Multi-route config and scheduling

*Goal: the data model the UI will drive.*

- `/data/routes.json` with a `schema_version` and a migration path from day one
- `/api/routes` CRUD, plus `/api/routes/{id}/preview`, `/api/status`, `/api/usage`
- Per-route fields: name, origin, destination, `avoid_tolls`, `poll_interval`, active windows,
  enabled
- Scheduler honours windows; entities gain `stale` and `in_active_window`
- Dynamic MQTT discovery: adding a route creates entities live, and deleting one publishes empty
  retained configs so the entities disappear cleanly

**Done when:** three routes with different toll settings and windows produce correct entities and
poll only inside their windows.

### M4 — Ingress UI

*Goal: the requirement that the user can see and choose their route.*

- Route list with live status, and an add/edit form with geocoded address autocomplete
- Leaflet map on OSM tiles, drawing all alternatives at once — the chosen route highlighted,
  the others muted, each labelled with duration, delay, distance and toll status. Click to select.
- Tolls toggle, schedule editor, and the **projected monthly API usage** readout
- Ingress-aware paths: everything relative, since ingress serves under a generated prefix. A
  dark-mode-aware palette so it doesn't glare inside the HA frame.
- Mobile layout, because the companion app is how most people will open this

**Done when:** a user can add a route, see alternatives on the map, pick a non-optimal one, save
it, and watch its entities appear — without touching YAML.

### M5 — Route pinning

*Goal: the chosen route stays the chosen route.* See section 5.

- Polyline downsampling and storage on selection
- POST reconstruction path in the provider, with the GET path retained for re-scans
- A "re-scan alternatives" action in the UI
- Test: a pinned slower route must keep reporting the slower road when traffic inverts the ranking

**Done when:** that test passes against recorded fixtures representing both traffic states.

### M6 — Release

- Multi-arch build and GitHub Actions CI: lint, test, build every arch
- `DOCS.md`, `CHANGELOG.md`, and a README with a one-click repo-add button
- A get-an-API-key walkthrough with screenshots — the most likely place a new user stalls
- Add-on `image:` pointing at GHCR, so users pull rather than build on a Pi
- Version pin, tag, publish

---

## 7. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Free tier changes or is withdrawn | High | D6's provider interface; the budget guard makes overruns visible before they cost money |
| TomTom coverage is weak in the user's region | Medium | Validate early in M1 with the user's real commute, not synthetic addresses |
| Route pinning drifts over time | Medium | M5's inverted-traffic fixture test; expose the pinned polyline as an attribute so drift is visible on a map card |
| MQTT broker absent | Medium | `mqtt:want`, not `need`; detect it and show a clear setup message in the UI instead of failing silently |
| Rate limit (5 req/s) hit by a startup burst | Low | Semaphore plus a jittered stagger across routes |
| Ingress path assumptions break the UI | Low | Strictly relative URLs, and test through ingress from M0 onward — never via a direct port |

---

## 8. Suggested sequencing

M0 → M1 → M2 is strictly sequential and worth doing in a single push: it retires every
integration risk and ends with a working sensor. After that, M3 → M4 is the bulk of the work,
and M5 can run in parallel with M4's polish, since it touches only the provider and storage
layers.

The single most useful thing to do before writing any code beyond M0 is to confirm that a
TomTom key returns sensible results for a real route in the user's own region.
