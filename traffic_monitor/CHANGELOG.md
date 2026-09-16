# Changelog

## 0.4.0

- Ingress UI (M4): the add-on now has a real UI, replacing raw API calls
  as the way to manage routes. Vanilla JS + Leaflet, no build step,
  Leaflet vendored locally rather than pulled from a CDN. Every asset
  reference and API call uses a purely relative path (no leading slash)
  since Home Assistant serves ingress add-ons under a per-session token
  prefix that only relative-URL resolution respects correctly.
  - Route list with live status (duration/delay/distance/traffic-level
    badge), an inline disable/enable toggle, edit and delete.
  - Add/edit form with a day-of-week + time-window schedule editor.
  - "Preview route" calls the real routing API and draws every
    alternative on a Leaflet/OSM map -- the selected one highlighted,
    others muted -- with a matching list underneath; clicking either the
    map or the list re-picks which alternative is highlighted.
  - A monthly API usage bar (color-coded at the warning/exhausted
    thresholds) and a banner when the API key or MQTT isn't set up yet.
  - Dark-mode-aware (`prefers-color-scheme`) and usable down to ~400px.
- New `app.models.Route.selected_alternative_points`: the polyline of
  whichever alternative the user picked in the preview, captured now so
  M5's route pinning has something to reconstruct against. Not yet
  consumed by the scheduler -- until M5, every poll still calculates
  fresh regardless of what's stored here.
- New `GET /api/routes/status` and `GET /api/routes/{id}/status`: the
  last-published state for one or all routes, backed by a small cache
  `MqttPublisher` now keeps of every payload it publishes. This is what
  lets the ingress UI show "live" status over plain HTTP without an MQTT
  client in the browser -- reusing the exact same payload MQTT sees, not
  a second implementation of it.
- 10 new offline tests (the status cache, the new endpoints,
  `selected_alternative_points` round-tripping through the API).
  101/101 total pass offline.

Verified in a real headless browser (Playwright), not just curl: drove
the actual running app through creating a route end to end -- opened the
form, filled in the user's real commute addresses, clicked "Preview
route" (a genuine TomTom API call), confirmed 6 alternatives rendered as
distinct polylines on the map with a matching list, clicked a different
alternative and confirmed both the map and the list highlight moved
together, saved, and confirmed the new route appeared in the list with
its live status once polled. Zero browser console errors. This caught a
real bug before it shipped: every asset reference in the HTML was
missing the `static/` prefix main.py actually mounts static files under,
so nothing but the page shell itself loaded (fixed by correcting the
references, not by changing the server's routing). A second real bug --
a CSS flex-basis that meant something different once a mobile media
query switched `.route-card` to a column layout, visibly inflating every
card -- was caught from screenshots and fixed, then re-verified with
another real run.

## 0.3.0

- Multi-route config and scheduling (M3): routes are now managed through a
  full CRUD API (`GET/POST /api/routes`, `GET/PUT/DELETE /api/routes/{id}`),
  persisted in `/data/routes.json`, instead of the single hardcoded route
  in add-on options. Adding a route starts its own poll task and publishes
  its MQTT discovery configs immediately; deleting one stops its task and
  retracts its entities from HA (empty retained payloads on its discovery
  and state topics). `route_name`/`route_origin`/`route_destination`/etc.
  in the add-on options are now only a one-time migration seed for
  upgrading M2 installs, not the primary configuration path.
- Active-window scheduling: each route carries a `schedule` (days of week
  + time windows). A route outside its window is never polled -- this is
  what makes many routes fit inside TomTom's free tier (see ROADMAP.md
  section 2). Its entities keep their last known value with `stale: true`
  and `in_active_window: false` attributes rather than going blank.
- New `POST /api/routes/preview` (geocode + calculate a route with
  alternatives and full geometry without saving it -- what the M4 map UI
  will use to show alternatives before committing) and `GET /api/usage`
  (the budget guard's figures, as JSON).
- 50 new offline tests (route store CRUD/persistence/migration, schedule
  window logic, manager task lifecycle against an injectable fake poller,
  and the full API surface via TestClient). 91/91 total pass offline.

Verified against real infrastructure: created three routes via the actual
running API (tolls allowed, tolls avoided, and one with a currently-closed
window) against a local Mosquitto broker and the real TomTom API. Confirmed
on the wire: the tolls-avoided route reported a real ~10-minute cost versus
the tolls-allowed route; the windowed route's discovery configs (and thus
its HA device/entities) existed but it never polled and published no state
at all, exactly as designed; deleting a route correctly cleared its
retained MQTT messages while leaving the other two untouched; and
`routes.json` persisted correctly across the delete.

## 0.2.0

- Walking skeleton (M2): one route, configured directly in the add-on's
  Configuration tab (`route_name`/`route_origin`/`route_destination`/
  `route_avoid_tolls`/`route_poll_interval_minutes`), is geocoded, polled
  against TomTom on a fixed interval, and published to MQTT as a real HA
  device with 7 sensors (duration, typical duration, delay, incident
  delay, distance, ETA, traffic level), auto-discovered via MQTT
  Discovery. Availability is tracked via a Last Will, so entities go
  `unavailable` if the add-on stops uncleanly. MQTT connection details
  are auto-discovered from the Supervisor's `mqtt` service, with an
  optional manual override (`mqtt_host`/`mqtt_port`/`mqtt_username`/
  `mqtt_password`) for brokers outside the Supervisor's knowledge.
  Multi-route config and the map UI are still ahead -- see
  [ROADMAP.md](../ROADMAP.md) milestones M3-M5.

## 0.1.0

- Initial add-on scaffold (M0): installs on `amd64`/`aarch64`, starts under the
  Supervisor, serves a placeholder page through ingress, and exposes `/api/status`
  for a basic health check. No routing, MQTT entities, or route UI yet &mdash; see
  [ROADMAP.md](../ROADMAP.md) for what's next.
