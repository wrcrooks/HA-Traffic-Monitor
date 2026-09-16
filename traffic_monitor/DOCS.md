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
4. Start the add-on and open **Traffic Monitor** from the sidebar.
5. Click **+ Add Route**, fill in a name and your origin/destination addresses,
   click **Preview route** to see alternatives on the map, click one to pick it
   (or leave the fastest one selected), then **Save route**. Within a minute or
   so you'll see a new device (named after your route) with 7 sensors under
   **Settings &rarr; Devices & Services &rarr; MQTT**.

The `/api/routes` API below still works directly if you'd rather script it.

See the project [ROADMAP](https://github.com/wrcrooks/HA-Traffic-Monitor/blob/main/ROADMAP.md)
for what's coming next -- notably, picking a non-default alternative in the UI
doesn't yet make that specific route "stick" through changing traffic
conditions; that's route pinning, arriving in M5.

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
| `GET` | `/api/routes/status` / `/api/routes/{id}/status` | Last-published live state for one or all routes -- what the UI's route list reads. |
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
