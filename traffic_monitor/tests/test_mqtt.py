from __future__ import annotations

import asyncio
import json

import pytest

from app.models import RouteAlternative, RouteSummary, Route
from app.mqtt import (
    MqttConfig,
    MqttPublisher,
    availability_topic,
    build_discovery_config,
    build_state_payload,
    discovery_topic,
    state_topic,
)

ROUTE = Route(
    id="commute",
    name="My Commute",
    origin_address="Decker Farms, Magnolia, TX 77355",
    destination_address="22777 Springwoods Village Pkwy, Spring, TX 77389",
    avoid_tolls=False,
)

ROUTE_2 = Route(
    id="errand",
    name="Errand Run",
    origin_address="123 Main St",
    destination_address="456 Oak Ave",
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
    assert payload["stale"] is False
    assert payload["in_active_window"] is True


def test_build_state_payload_imperial_units():
    payload = build_state_payload(ROUTE, ALTERNATIVE, "imperial")
    assert payload["distance"] == pytest.approx(20.7, abs=0.05)  # miles, rounded to 1dp


def test_build_state_payload_stale_and_window_flags():
    payload = build_state_payload(ROUTE, ALTERNATIVE, "metric", stale=True, in_active_window=False)
    assert payload["stale"] is True
    assert payload["in_active_window"] is False


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
    assert "stale" in config["json_attributes_template"]
    assert "in_active_window" in config["json_attributes_template"]


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


def test_two_routes_get_distinct_topics_and_devices():
    a = build_discovery_config(ROUTE, "duration", "metric")
    b = build_discovery_config(ROUTE_2, "duration", "metric")
    assert a["unique_id"] != b["unique_id"]
    assert a["state_topic"] != b["state_topic"]
    assert a["device"]["identifiers"] != b["device"]["identifiers"]


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


async def test_run_publishes_availability_then_calls_on_connect_then_offline_on_stop():
    fake_client = FakeMqttClient()
    publisher = MqttPublisher(MqttConfig(host="broker"), client_factory=lambda: fake_client)
    stop_event = asyncio.Event()
    on_connect_calls = []

    async def on_connect():
        on_connect_calls.append(True)
        await publisher.publish_discovery([ROUTE])

    task = asyncio.create_task(publisher.run(stop_event, on_connect=on_connect))
    await asyncio.sleep(0.01)  # let run() connect and call on_connect before we stop it
    stop_event.set()
    await asyncio.wait_for(task, timeout=1)

    assert on_connect_calls == [True]
    topics_in_order = [t for t, _, _ in fake_client.published]
    assert topics_in_order[0] == availability_topic()
    assert fake_client.published[0][1] == "online"
    assert fake_client.published[0][2] is True  # retained

    assert discovery_topic("commute", "duration") in topics_in_order
    assert discovery_topic("commute", "traffic_level") in topics_in_order
    for topic, payload, retain in fake_client.published[1:-1]:
        assert retain is True
        json.loads(payload)  # must be valid JSON

    assert topics_in_order[-1] == availability_topic()
    assert fake_client.published[-1][1] == "offline"


async def test_publish_discovery_for_two_routes_is_independent():
    fake_client = FakeMqttClient()
    publisher = MqttPublisher(MqttConfig(host="broker"), client_factory=lambda: fake_client)
    publisher._client = fake_client

    await publisher.publish_discovery([ROUTE, ROUTE_2])

    topics = {t for t, _, _ in fake_client.published}
    assert discovery_topic("commute", "duration") in topics
    assert discovery_topic("errand", "duration") in topics
    assert len(fake_client.published) == 14  # 7 metrics x 2 routes


async def test_clear_route_publishes_empty_retained_payloads():
    fake_client = FakeMqttClient()
    publisher = MqttPublisher(MqttConfig(host="broker"), client_factory=lambda: fake_client)
    publisher._client = fake_client

    await publisher.clear_route(ROUTE)

    assert len(fake_client.published) == 8  # 7 discovery configs + 1 state topic
    for topic, payload, retain in fake_client.published:
        assert payload == ""
        assert retain is True
    topics = {t for t, _, _ in fake_client.published}
    assert state_topic("commute") in topics
    assert discovery_topic("commute", "eta") in topics


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
