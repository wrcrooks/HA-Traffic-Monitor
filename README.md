# HA Traffic Monitor

A Home Assistant add-on that monitors drive time and live traffic conditions for
routes you define (a commute, a school run, whatever you drive regularly), exposes
them as MQTT-discovered entities, and gives you an ingress UI with a map for picking
which of several suggested routes you actually take.

Status: early development. See [ROADMAP.md](ROADMAP.md) for the plan and
[CLAUDE.md](CLAUDE.md) for the original requirements.

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**.
2. Click the **⋮** menu (top right) → **Repositories**.
3. Add this repository's URL: `https://github.com/wrcrooks/HA-Traffic-Monitor`
4. Find **Traffic Monitor** in the store and install it.
5. Get a free [TomTom Developer](https://developer.tomtom.com/) API key (no credit
   card required) and paste it into the add-on's **Configuration** tab.
6. Start the add-on and open it from the sidebar to add your first route.

## Requirements

- Home Assistant OS or Supervised, with the Mosquitto broker add-on (or another MQTT
  broker) installed and the MQTT integration configured.
- A free TomTom API key.

## Development

The add-on itself lives in [traffic_monitor/](traffic_monitor/). See
[traffic_monitor/DOCS.md](traffic_monitor/DOCS.md) for user-facing docs and
[ROADMAP.md](ROADMAP.md) for the milestone plan.
