# Changelog

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
