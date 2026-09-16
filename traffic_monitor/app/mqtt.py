"""
MQTT Discovery publisher (ROADMAP.md section 4).

Split deliberately into pure payload/topic builders (fully unit-testable
without a broker) and MqttPublisher, which owns one long-lived connection
for the add-on's lifetime and reconnects with backoff on failure.

Availability is a single shared topic with a Last Will, so entities go
`unavailable` rather than silently stale if the add-on dies uncleanly.
Only the `duration` sensor carries the shared route attributes
(route_name/origin/destination/avoid_tolls/last_updated/stale/
in_active_window) -- the other metrics on the same device would just be
duplicating them.

Discovery configs and state are published per-route rather than all at
once, since M3 adds/removes routes dynamically at runtime (see
manager.py) -- routes.json isn't a fixed set decided at startup anymore.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

import aiomqtt

from app.models import Route, RouteAlternative

logger = logging.getLogger("traffic_monitor.mqtt")

DISCOVERY_PREFIX = "homeassistant"

_DISTANCE_UNITS = {"metric": "km", "imperial": "mi"}

# metric -> discovery config fields
_METRICS: dict[str, dict] = {
    "duration": {
        "name": "Duration",
        "device_class": "duration",
        "unit_of_measurement": "min",
        "state_class": "measurement",
        "icon": "mdi:car-clock",
    },
    "duration_typical": {
        "name": "Typical Duration",
        "device_class": "duration",
        "unit_of_measurement": "min",
        "state_class": "measurement",
        "icon": "mdi:car-clock",
    },
    "delay": {
        "name": "Delay",
        "device_class": "duration",
        "unit_of_measurement": "min",
        "state_class": "measurement",
        "icon": "mdi:traffic-cone",
    },
    "incident_delay": {
        "name": "Incident Delay",
        "device_class": "duration",
        "unit_of_measurement": "min",
        "state_class": "measurement",
        "icon": "mdi:alert-octagon-outline",
    },
    "distance": {
        "name": "Distance",
        "device_class": "distance",
        "state_class": "measurement",
        "icon": "mdi:map-marker-distance",
    },
    "eta": {
        "name": "ETA",
        "device_class": "timestamp",
        "icon": "mdi:clock-check-outline",
    },
    "traffic_level": {
        "name": "Traffic Level",
        "device_class": "enum",
        "options": ["free_flow", "light", "moderate", "heavy"],
        "icon": "mdi:car-traffic-light",
    },
}

_VALUE_KEYS = {
    "duration": "duration_minutes",
    "duration_typical": "duration_typical_minutes",
    "delay": "delay_minutes",
    "incident_delay": "incident_delay_minutes",
    "distance": "distance",
    "eta": "eta",
    "traffic_level": "traffic_level",
}


# -- topics ------------------------------------------------------------------


def availability_topic() -> str:
    return "traffic_monitor/status"


def state_topic(route_id: str) -> str:
    return f"traffic_monitor/{route_id}/state"


def discovery_topic(route_id: str, metric: str) -> str:
    return f"{DISCOVERY_PREFIX}/sensor/traffic_monitor_{route_id}/{metric}/config"


# -- payload builders (pure) --------------------------------------------------


def device_info(route: Route) -> dict:
    return {
        "identifiers": [f"traffic_monitor_{route.id}"],
        "name": route.name,
        "manufacturer": "Traffic Monitor",
        "model": "Route",
    }


def build_discovery_config(route: Route, metric: str, unit_system: str) -> dict:
    spec = dict(_METRICS[metric])
    name = spec.pop("name")
    config = {
        "name": name,
        "unique_id": f"traffic_monitor_{route.id}_{metric}",
        "state_topic": state_topic(route.id),
        "value_template": f"{{{{ value_json.{_VALUE_KEYS[metric]} }}}}",
        "availability_topic": availability_topic(),
        "device": device_info(route),
        **spec,
    }
    if metric == "distance":
        config["unit_of_measurement"] = _DISTANCE_UNITS.get(unit_system, "km")
    if metric == "duration":
        config["json_attributes_topic"] = state_topic(route.id)
        config["json_attributes_template"] = (
            "{{ {'route_name': value_json.route_name, 'origin': value_json.origin, "
            "'destination': value_json.destination, 'avoid_tolls': value_json.avoid_tolls, "
            "'last_updated': value_json.last_updated, 'stale': value_json.stale, "
            "'in_active_window': value_json.in_active_window} | tojson }}"
        )
    return config


def build_state_payload(
    route: Route,
    alternative: RouteAlternative,
    unit_system: str,
    *,
    stale: bool = False,
    in_active_window: bool = True,
) -> dict:
    s = alternative.summary
    distance = s.length_meters / 1609.34 if unit_system == "imperial" else s.length_meters / 1000.0
    eta = s.arrival_time.isoformat() if s.arrival_time else None
    return {
        "duration_minutes": round(s.duration_seconds / 60, 1),
        "duration_typical_minutes": round(s.duration_typical_seconds / 60, 1),
        "delay_minutes": round(s.delay_seconds / 60, 1),
        "incident_delay_minutes": round(s.incident_delay_seconds / 60, 1),
        "distance": round(distance, 1),
        "eta": eta,
        "traffic_level": s.traffic_level.value,
        "last_updated": datetime.now().astimezone().isoformat(),
        "route_name": route.name,
        "origin": route.origin_address,
        "destination": route.destination_address,
        "avoid_tolls": route.avoid_tolls,
        "stale": stale,
        "in_active_window": in_active_window,
    }


# -- connection ----------------------------------------------------------


@dataclass
class MqttConfig:
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    client_id: str = "traffic_monitor"


class MqttPublisher:
    def __init__(
        self,
        config: MqttConfig,
        unit_system: str = "metric",
        client_factory: Callable[[], aiomqtt.Client] | None = None,
    ) -> None:
        self._config = config
        self._unit_system = unit_system
        self._client_factory = client_factory or self._default_client_factory
        self._client: aiomqtt.Client | None = None

    def _default_client_factory(self) -> aiomqtt.Client:
        will = aiomqtt.Will(topic=availability_topic(), payload="offline", qos=1, retain=True)
        return aiomqtt.Client(
            hostname=self._config.host,
            port=self._config.port,
            username=self._config.username,
            password=self._config.password,
            identifier=self._config.client_id,
            will=will,
        )

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def run(
        self,
        stop_event: asyncio.Event,
        on_connect: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Owns the MQTT connection for as long as stop_event isn't set:
        connects, publishes availability, then calls `on_connect` (which
        RouteManager uses to (re)publish discovery configs for every
        currently-known route -- both on first connect and after any
        reconnect, since a broker that lost its retained-message store
        needs them republished) before holding the connection open for
        publish_state()/publish_discovery()/clear_route() to use from
        other tasks. Reconnects with exponential backoff on MqttError."""
        backoff = 1.0
        while not stop_event.is_set():
            try:
                async with self._client_factory() as client:
                    self._client = client
                    backoff = 1.0
                    logger.info("Connected to MQTT broker at %s:%d", self._config.host, self._config.port)
                    await client.publish(availability_topic(), "online", retain=True)
                    if on_connect:
                        await on_connect()
                    await stop_event.wait()
                    await client.publish(availability_topic(), "offline", retain=True)
                    return
            except aiomqtt.MqttError as exc:
                logger.warning("MQTT connection lost (%s) -- reconnecting in %.0fs", exc, backoff)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60.0)
            finally:
                self._client = None

    async def publish_discovery(self, routes: list[Route]) -> None:
        """Publishes (or re-publishes) retained discovery configs for the
        given routes. Called for all routes on every (re)connect, and for
        a single route right after it's created or updated through the
        API (manager.py)."""
        if self._client is None:
            logger.warning("MQTT not connected -- cannot publish discovery configs")
            return
        for route in routes:
            for metric in _METRICS:
                cfg = build_discovery_config(route, metric, self._unit_system)
                await self._client.publish(discovery_topic(route.id, metric), json.dumps(cfg), retain=True)

    async def clear_route(self, route: Route) -> None:
        """Removes a deleted route's entities from HA by publishing empty
        retained payloads to its discovery and state topics -- the
        standard MQTT Discovery convention for retracting a device."""
        if self._client is None:
            logger.warning("MQTT not connected -- cannot clear entities for %r", route.name)
            return
        for metric in _METRICS:
            await self._client.publish(discovery_topic(route.id, metric), "", retain=True)
        await self._client.publish(state_topic(route.id), "", retain=True)

    async def publish_state(
        self,
        route: Route,
        alternative: RouteAlternative,
        *,
        stale: bool = False,
        in_active_window: bool = True,
    ) -> None:
        if self._client is None:
            logger.warning("MQTT not connected -- dropping state update for %r", route.name)
            return
        payload = build_state_payload(
            route, alternative, self._unit_system, stale=stale, in_active_window=in_active_window
        )
        # Retained so a sensor shows its last known value immediately after
        # an HA restart, rather than "unknown" until the next poll.
        await self._client.publish(state_topic(route.id), json.dumps(payload), retain=True)
