# Traffic Monitor

Monitor drive time and live traffic conditions for routes you define, and pick which
of several suggested routes you actually drive.

## Getting started

1. Get a free [TomTom Developer](https://developer.tomtom.com/) API key. No credit
   card is required for the free tier (20,000 requests/month).
2. Open this add-on's **Configuration** tab and fill in **API Key**.
3. Make sure an MQTT broker is running (the **Mosquitto broker** add-on works) and
   the MQTT integration is set up in Home Assistant. Traffic Monitor discovers it
   automatically and does not need separate MQTT settings.
4. Start the add-on.
5. v0.3 manages routes through an API (`/api/routes`) rather than a UI &mdash;
   a proper ingress UI with a map for picking among suggested alternatives
   arrives in a later release. Until then, add a route with:
   ```
   curl -X POST http://<home-assistant>:8099/api/routes \
     -H "Content-Type: application/json" \
     -d '{"name": "My Commute", "origin_address": "...", "destination_address": "...", "avoid_tolls": false}'
   ```
   (adjust the host/port for how you reach the add-on's ingress). Within a minute
   or so you'll see a new device (named after your route) with 7 sensors under
   **Settings &rarr; Devices & Services &rarr; MQTT**.

See the project [ROADMAP](https://github.com/wrcrooks/HA-Traffic-Monitor/blob/main/ROADMAP.md)
for what's coming next.

## Configuration options

| Option | Description |
|---|---|
| `api_key` | Your TomTom API key. |
| `unit_system` | `metric` or `imperial`. Controls the units shown for distance. |
| `log_level` | Add-on log verbosity: `trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal`. |
| `mqtt_host` / `mqtt_port` / `mqtt_username` / `mqtt_password` | Optional. Only needed if your MQTT broker isn't discoverable via the Supervisor's `mqtt` service. |
| `route_name` / `route_origin` / `route_destination` / `route_avoid_tolls` / `route_poll_interval_minutes` | Legacy: only used once, as a one-time migration seed if upgrading from v0.2 with routes.json still empty. Leave blank otherwise -- manage routes via the API. |

## Routes API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/routes` | List all routes. |
| `POST` | `/api/routes` | Create a route. Body: `name`, `origin_address`, `destination_address`, `avoid_tolls`, `poll_interval_minutes` (1-1440), `schedule` (`{"days": [0-6, Mon=0], "windows": [{"start": "HH:MM", "end": "HH:MM"}]}`, omit for "always active"), `enabled`. |
| `GET` / `PUT` / `DELETE` | `/api/routes/{id}` | Fetch, replace, or remove a single route. Deleting removes its entities from HA immediately. |
| `POST` | `/api/routes/preview` | Geocode + calculate a route (with alternatives and full geometry) without saving it. Spends API budget like a real poll. |
| `GET` | `/api/usage` | Current TomTom API budget: `used_30d`, `remaining`, `monthly_limit`, `usage_ratio`, `warning`, `exhausted`. |

## Entities

Each route gets its own device with these sensors: **Duration** (current drive time),
**Typical Duration** (free-flow baseline), **Delay** (how much longer than typical,
right now -- the one most automations should use), **Incident Delay** (TomTom's
own incident-relative metric, usually 0 outside genuine accidents/closures),
**Distance**, **ETA**, and **Traffic Level** (`free_flow`/`light`/`moderate`/`heavy`).

The Duration sensor also carries `route_name`, `origin`, `destination`, `avoid_tolls`,
`last_updated`, `stale`, and `in_active_window` as attributes. A route outside its
configured active window (or one that failed to poll) keeps reporting its last known
values with `stale: true` rather than going blank.

## API usage

The free TomTom tier allows 20,000 requests/month. Traffic Monitor tracks usage
internally on a rolling 30-day basis (`GET /api/usage`) and will stop polling before
exceeding your budget. Give a route a `schedule` with specific active windows (e.g.
weekday rush hours only) to make many routes fit comfortably inside the free tier --
see the ROADMAP for the numbers behind this.

## Support

This add-on is under active development. Please file issues on
[GitHub](https://github.com/wrcrooks/HA-Traffic-Monitor/issues).
