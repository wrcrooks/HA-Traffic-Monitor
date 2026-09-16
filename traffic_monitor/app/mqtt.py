"""
MQTT Discovery publisher (ROADMAP.md section 4).

Split deliberately into pure payload/topic builders (fully unit-testable
without a broker) and MqttPublisher, which owns one long-lived connection
for the add-on's lifetime and reconnects with backoff on failure.

Availability is a single shared topic with a Last Will, so entities go
`unavailable` rather than silently stale if the add-on dies uncleanly.
Only the `duration` sensor carries the shared route attributes
(route_name/origin/destination/avoid_tolls/last_updated) -- the other
metrics on the same device would just be duplicating them.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import aiomqtt

from app.models import RouteAlternative, RouteConfig

logger = logging.getLogger("traffic_monitor.mqtt")

DISCOVERY_PREFIX = "homeassistant"

_DISTANCE_UNITS = {"metric": "km", "imperial": "mi"}

# metric -> (discovery config fields, key read from the state JSON payload)
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


def device_info(route: RouteConfig) -> dict:
    return {
        "identifiers": [f"traffic_monitor_{route.route_id}"],
        "name": route.name,
        "manufacturer": "Traffic Monitor",
        "model": "Route",
    }


def build_discovery_config(route: RouteConfig, metric: str, unit_system: str) -> dict:
    spec = dict(_METRICS[metric])
    name = spec.pop("name")
    config = {
        "name": name,
        "unique_id": f"traffic_monitor_{route.route_id}_{metric}",
        "state_topic": state_topic(route.route_id),
        "value_template": f"{{{{ value_json.{_VALUE_KEYS[metric]} }}}}",
        "availability_topic": availability_topic(),
        "device": device_info(route),
        **spec,
    }
    if metric == "distance":
        config["unit_of_measurement"] = _DISTANCE_UNITS.get(unit_system, "km")
    if metric == "duration":
        config["json_attributes_topic"] = state_topic(route.route_id)
        config["json_attributes_template"] = (
            "{{ {'route_name': value_json.route_name, 'origin': value_json.origin, "
            "'destination': value_json.destination, 'avoid_tolls': value_json.avoid_tolls, "
            "'last_updated': value_json.last_updated} | tojson }}"
        )
    return config


def build_state_payload(route: RouteConfig, alternative: RouteAlternative, unit_system: str) -> dict:
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

    async def run(self, routes: list[RouteConfig], stop_event: asyncio.Event) -> None:
        """Owns the MQTT connection for as long as stop_event isn't set:
        connects, publishes discovery configs + availability, then holds
        the connection open (so publish_state() can use it from another
        task) until told to stop. Reconnects with exponential backoff on
        MqttError -- the broker restarting shouldn't take the add-on down."""
        backoff = 1.0
        while not stop_event.is_set():
            try:
                async with self._client_factory() as client:
                    self._client = client
                    backoff = 1.0
                    logger.info("Connected to MQTT broker at %s:%d", self._config.host, self._config.port)
                    await client.publish(availability_topic(), "online", retain=True)
                    for route in routes:
                        for metric in _METRICS:
                            cfg = build_discovery_config(route, metric, self._unit_system)
                            await client.publish(
                                discovery_topic(route.route_id, metric), json.dumps(cfg), retain=True
                            )
                    await stop_event.wait()
                    await client.publish(availability_topic(), "offline", retain=True)
                    return
            except aiomqtt.MqttError as exc:
                self._client = None
                logger.warning("MQTT connection lost (%s) -- reconnecting in %.0fs", exc, backoff)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60.0)
            finally:
                self._client = None

    async def publish_state(self, route: RouteConfig, alternative: RouteAlternative) -> None:
        if self._client is None:
            logger.warning("MQTT not connected -- dropping state update for %r", route.name)
            return
        payload = build_state_payload(route, alternative, self._unit_system)
        # Retained so a sensor shows its last known value immediately after
        # an HA restart, rather than "unknown" until the next poll.
        await self._client.publish(state_topic(route.route_id), json.dumps(payload), retain=True)
