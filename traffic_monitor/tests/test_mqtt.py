from __future__ import annotations

import asyncio
import json

import pytest

from app.models import GeoPoint, RouteAlternative, RouteConfig, RouteSummary
from app.mqtt import (
    MqttConfig,
    MqttPublisher,
    availability_topic,
    build_discovery_config,
    build_state_payload,
    discovery_topic,
    state_topic,
)

ROUTE = RouteConfig(
    route_id="commute",
    name="My Commute",
    origin_address="Decker Farms, Magnolia, TX 77355",
    destination_address="22777 Springwoods Village Pkwy, Spring, TX 77389",
    avoid_tolls=False,
)

ALTERNATIVE = RouteAlternative(
    index=0,
    summary=RouteSummary(
        duration_seconds=1702,
        duration_typical_seconds=1535,
        incident_delay_seconds=0,
        length_meters=33370,
    ),
)


# -- pure builders -----------------------------------------------------------


def test_build_state_payload_metric_units():
    payload = build_state_payload(ROUTE, ALTERNATIVE, "metric")
    assert payload["duration_minutes"] == pytest.approx(28.4, abs=0.05)
    assert payload["duration_typical_minutes"] == pytest.approx(25.6, abs=0.05)
    assert payload["delay_minutes"] == pytest.approx(2.8, abs=0.05)
    assert payload["distance"] == pytest.approx(33.4, abs=0.05)  # km, rounded to 1dp
    assert payload["traffic_level"] == "light"
    assert payload["route_name"] == "My Commute"
    assert payload["avoid_tolls"] is False


def test_build_state_payload_imperial_units():
    payload = build_state_payload(ROUTE, ALTERNATIVE, "imperial")
    assert payload["distance"] == pytest.approx(20.7, abs=0.05)  # miles, rounded to 1dp


def test_build_discovery_config_duration_carries_shared_attributes():
    config = build_discovery_config(ROUTE, "duration", "metric")
    assert config["unique_id"] == "traffic_monitor_commute_duration"
    assert config["state_topic"] == state_topic("commute")
    assert config["value_template"] == "{{ value_json.duration_minutes }}"
    assert config["device_class"] == "duration"
    assert config["unit_of_measurement"] == "min"
    assert config["availability_topic"] == availability_topic()
    assert config["device"]["identifiers"] == ["traffic_monitor_commute"]
    assert "json_attributes_topic" in config


def test_build_discovery_config_other_metrics_skip_shared_attributes():
    config = build_discovery_config(ROUTE, "delay", "metric")
    assert "json_attributes_topic" not in config


def test_build_discovery_config_distance_unit_follows_unit_system():
    assert build_discovery_config(ROUTE, "distance", "metric")["unit_of_measurement"] == "km"
    assert build_discovery_config(ROUTE, "distance", "imperial")["unit_of_measurement"] == "mi"


def test_build_discovery_config_traffic_level_is_enum_with_options():
    config = build_discovery_config(ROUTE, "traffic_level", "metric")
    assert config["device_class"] == "enum"
    assert set(config["options"]) == {"free_flow", "light", "moderate", "heavy"}


# -- MqttPublisher, against a fake client (no real broker needed) ------------


class FakeMqttClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, bool]] = []

    async def __aenter__(self) -> "FakeMqttClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def publish(self, topic: str, payload=None, retain: bool = False, **kwargs) -> None:
        self.published.append((topic, payload, retain))


async def test_run_publishes_availability_and_discovery_then_offline_on_stop():
    fake_client = FakeMqttClient()
    publisher = MqttPublisher(MqttConfig(host="broker"), client_factory=lambda: fake_client)
    stop_event = asyncio.Event()

    task = asyncio.create_task(publisher.run([ROUTE], stop_event))
    await asyncio.sleep(0.01)  # let run() connect and publish discovery before we stop it
    stop_event.set()
    await asyncio.wait_for(task, timeout=1)

    topics_in_order = [t for t, _, _ in fake_client.published]
    assert topics_in_order[0] == availability_topic()
    assert fake_client.published[0][1] == "online"
    assert fake_client.published[0][2] is True  # retained

    assert discovery_topic("commute", "duration") in topics_in_order
    assert discovery_topic("commute", "traffic_level") in topics_in_order
    # every discovery publish is retained
    for topic, payload, retain in fake_client.published[1:-1]:
        assert retain is True
        json.loads(payload)  # must be valid JSON

    assert topics_in_order[-1] == availability_topic()
    assert fake_client.published[-1][1] == "offline"


async def test_publish_state_sends_retained_json_to_state_topic():
    fake_client = FakeMqttClient()
    publisher = MqttPublisher(MqttConfig(host="broker"), client_factory=lambda: fake_client)
    publisher._client = fake_client  # simulate an already-connected publisher

    await publisher.publish_state(ROUTE, ALTERNATIVE)

    assert len(fake_client.published) == 1
    topic, payload, retain = fake_client.published[0]
    assert topic == state_topic("commute")
    assert retain is True
    body = json.loads(payload)
    assert body["duration_minutes"] == pytest.approx(28.4, abs=0.05)


async def test_publish_state_without_connection_does_not_raise():
    publisher = MqttPublisher(MqttConfig(host="broker"), client_factory=FakeMqttClient)
    # never connected -- publisher._client stays None
    await publisher.publish_state(ROUTE, ALTERNATIVE)  # should log and return, not raise
