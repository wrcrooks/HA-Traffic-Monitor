# Traffic Monitor

Monitor drive time and live traffic conditions for routes you define, and pick which
of several suggested routes you actually drive.

## Getting started

1. Get a free [TomTom Developer](https://developer.tomtom.com/) API key. No credit
   card is required for the free tier (20,000 requests/month).
2. Open this add-on's **Configuration** tab and paste the key into **API Key**.
3. Make sure an MQTT broker is running (the **Mosquitto broker** add-on works) and
   the MQTT integration is set up in Home Assistant. Traffic Monitor discovers it
   automatically and does not need separate MQTT settings.
4. Start the add-on and open **Traffic Monitor** from the sidebar.
5. Add a route (v0.1 does not yet expose the route UI &mdash; this arrives in a
   later release; see the project [ROADMAP](https://github.com/wrcrooks/HA-Traffic-Monitor/blob/main/ROADMAP.md)).

## Configuration options

| Option | Description |
|---|---|
| `api_key` | Your TomTom API key. |
| `unit_system` | `metric` or `imperial`. Controls the units shown for distance. |
| `log_level` | Add-on log verbosity: `trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal`. |

## API usage

The free TomTom tier allows 20,000 requests/month. Traffic Monitor tracks usage and
will stop polling before exceeding your budget; a diagnostic sensor reports requests
remaining. See the ROADMAP for how polling windows are used to make many routes fit
inside the free tier.

## Support

This add-on is under active development. Please file issues on
[GitHub](https://github.com/wrcrooks/HA-Traffic-Monitor/issues).
