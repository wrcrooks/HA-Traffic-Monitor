# Changelog

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
