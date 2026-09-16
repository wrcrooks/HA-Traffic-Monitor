# Traffic Monitor

Monitor drive time and live traffic conditions for routes you define, and pick which
of several suggested routes you actually drive.

## Getting started

1. Get a free [TomTom Developer](https://developer.tomtom.com/) API key. No credit
   card is required for the free tier (20,000 requests/month).
2. Open this add-on's **Configuration** tab and fill in **API Key**, **Route Origin**,
   and **Route Destination**.
3. Make sure an MQTT broker is running (the **Mosquitto broker** add-on works) and
   the MQTT integration is set up in Home Assistant. Traffic Monitor discovers it
   automatically and does not need separate MQTT settings.
4. Start the add-on. Within a minute or so you'll see a new device (named after
   your route) with 7 sensors under **Settings &rarr; Devices & Services &rarr;
   MQTT**.
5. v0.2 supports exactly **one** route, configured here in this tab. Adding as
   many routes as you like, from a proper UI with a map for picking among
   suggested alternatives, arrives in a later release &mdash; see the project
   [ROADMAP](https://github.com/wrcrooks/HA-Traffic-Monitor/blob/main/ROADMAP.md).

## Configuration options

| Option | Description |
|---|---|
| `api_key` | Your TomTom API key. |
| `unit_system` | `metric` or `imperial`. Controls the units shown for distance. |
| `log_level` | Add-on log verbosity: `trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal`. |
| `route_name` | Display name for the route's device and entities. |
| `route_origin` / `route_destination` | Addresses for your route. Free-text, geocoded automatically. |
| `route_avoid_tolls` | Avoid toll roads when calculating the route. |
| `route_poll_interval_minutes` | How often to check traffic (1-1440 minutes). Every API check counts against your monthly TomTom quota -- see below. |
| `mqtt_host` / `mqtt_port` / `mqtt_username` / `mqtt_password` | Optional. Only needed if your MQTT broker isn't discoverable via the Supervisor's `mqtt` service. |

## Entities

Each route gets its own device with these sensors: **Duration** (current drive time),
**Typical Duration** (free-flow baseline), **Delay** (how much longer than typical,
right now -- the one most automations should use), **Incident Delay** (TomTom's
own incident-relative metric, usually 0 outside genuine accidents/closures),
**Distance**, **ETA**, and **Traffic Level** (`free_flow`/`light`/`moderate`/`heavy`).

## API usage

The free TomTom tier allows 20,000 requests/month. Traffic Monitor tracks usage
internally on a rolling 30-day basis and will stop polling before exceeding your
budget (a dedicated usage sensor is planned -- for now, check the add-on log).
See the ROADMAP for how polling windows will make many routes fit inside the free
tier once multi-route support lands.

## Support

This add-on is under active development. Please file issues on
[GitHub](https://github.com/wrcrooks/HA-Traffic-Monitor/issues).
