import threading
import time
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from okam_bridge.onvif_events import (
    EventBroker,
    TOPICS,
    NAMESPACES,
    DIALECT,
    handle_events,
)


class EventBrokerTests(unittest.TestCase):
    def setUp(self):
        self.broker = EventBroker()

    def test_real_state_initialization_and_copy(self):
        key = self.broker.subscribe("a")
        self.assertEqual(self.broker.pull("a", key), [])
        original = {"IsMotion": True}
        returned = self.broker.publish(
            "a", TOPICS[0], {"VideoSourceConfigurationToken": "lens0"}, original
        )
        original["IsMotion"] = False
        returned["data"]["IsMotion"] = False
        event = self.broker.pull("a", key)[0]
        self.assertIs(event["data"]["IsMotion"], True)
        second = self.broker.subscribe("a")
        self.assertEqual(self.broker.pull("a", second)[0]["operation"], "Initialized")
        self.broker.synchronize("a", key)
        self.assertEqual(self.broker.pull("a", key)[0]["operation"], "Initialized")

    def test_export_scope_and_revocation(self):
        key = self.broker.subscribe("a")
        for operation in (
            lambda: self.broker.pull("b", key),
            lambda: self.broker.renew("b", key),
            lambda: self.broker.unsubscribe("b", key),
        ):
            with self.assertRaises(ValueError):
                operation()
        self.broker.drop("a")
        with self.assertRaises(ValueError):
            self.broker.pull("a", key)
        replacement = self.broker.subscribe("a")
        self.assertEqual(self.broker.pull("a", replacement), [])

    def test_ttl_renew_and_caps(self):
        with patch("okam_bridge.onvif_events.time.monotonic", return_value=100):
            key = self.broker.subscribe("a", ttl=2)
        with patch("okam_bridge.onvif_events.time.monotonic", return_value=101):
            self.broker.renew("a", key, ttl=3)
        with patch("okam_bridge.onvif_events.time.monotonic", return_value=103):
            self.assertEqual(self.broker.pull("a", key), [])
        with patch("okam_bridge.onvif_events.time.monotonic", return_value=105):
            with self.assertRaises(ValueError):
                self.broker.pull("a", key)
        key = self.broker.subscribe("a", ttl=10000)
        self.assertLessEqual(
            (
                self.broker.termination("a", key) - datetime.now(timezone.utc)
            ).total_seconds(),
            3600,
        )

    def test_long_poll_cancelled_by_drop(self):
        key = self.broker.subscribe("a")
        errors = []
        started = threading.Event()

        def wait():
            started.set()
            try:
                self.broker.pull("a", key, timeout=30)
            except ValueError as error:
                errors.append(error)

        thread = threading.Thread(target=wait)
        thread.start()
        self.assertTrue(started.wait(1))
        self.broker.drop("a")
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)

    def test_bounded_history_and_subscriptions(self):
        key = self.broker.subscribe("a")
        for i in range(300):
            self.broker.publish("a", TOPICS[1], {"rawAlarm": "alarm"}, {"State": i})
        first = self.broker.pull("a", key, limit=10000)
        self.assertEqual(len(first), 100)
        self.assertEqual(first[0]["data"]["State"], 44)
        self.assertEqual(len(self.broker.pull("a", key)), 100)
        self.assertEqual(len(self.broker.pull("a", key)), 56)
        for _ in range(31):
            self.broker.subscribe("a")
        with self.assertRaises(ValueError):
            self.broker.subscribe("a")
        for i in range(15):
            for _ in range(32):
                self.broker.subscribe(str(i))
        with self.assertRaises(ValueError):
            self.broker.subscribe("overflow")

    def test_topic_filter(self):
        key = self.broker.subscribe("a", topics=[TOPICS[0]])
        self.broker.publish("a", TOPICS[1], {}, {"State": "active"})
        self.assertEqual(self.broker.pull("a", key), [])
        self.broker.publish("a", TOPICS[0], {}, {"IsMotion": False})
        self.assertEqual(len(self.broker.pull("a", key)), 1)


class SOAPEventTests(unittest.TestCase):
    def setUp(self):
        self.registry = SimpleNamespace(events=EventBroker())
        self.item = {
            "export_id": "a",
            "advertise_host": "127.0.0.1",
            "onvif_port": 8899,
        }

    def call(self, action, content="", key=None):
        ns = "wsnt" if action in ("Renew", "Unsubscribe") else "tev"
        request = ET.fromstring(
            f'<{ns}:{action} xmlns:tev="{NAMESPACES["tev"]}" xmlns:wsnt="{NAMESPACES["wsnt"]}">{content}</{ns}:{action}>'
        )
        response = ET.Element("{" + NAMESPACES[ns] + "}" + action + "Response")
        handle_events(response, action, self.item, request, self.registry, key)
        return ET.fromstring(ET.tostring(response))

    def test_subscription_round_trip_and_notifications(self):
        response = self.call(
            "CreatePullPointSubscription",
            "<tev:InitialTerminationTime>PT60S</tev:InitialTerminationTime>",
        )
        address = response.find(".//wsa:Address", NAMESPACES).text
        self.assertTrue(
            address.startswith("http://127.0.0.1:8899/onvif/a/subscriptions/")
        )
        key = address.rsplit("/", 1)[-1]
        self.registry.events.publish(
            "a",
            TOPICS[0],
            {"VideoSourceConfigurationToken": "lens0"},
            {"IsMotion": True},
        )
        response = self.call(
            "PullMessages",
            "<tev:Timeout>PT0S</tev:Timeout><tev:MessageLimit>10</tev:MessageLimit>",
            key,
        )
        notification = response.find("wsnt:NotificationMessage", NAMESPACES)
        self.assertEqual(
            notification.find("wsnt:Topic", NAMESPACES).get("Dialect"), DIALECT
        )
        msg = notification.find(".//tt:Message", NAMESPACES)
        self.assertEqual(msg.get("PropertyOperation"), "Changed")
        self.assertEqual(
            msg.find(".//tt:Data/tt:SimpleItem", NAMESPACES).get("Value"), "true"
        )
        self.call("SetSynchronizationPoint", key=key)
        response = self.call("PullMessages", key=key)
        self.assertEqual(
            response.find(".//tt:Message", NAMESPACES).get("PropertyOperation"),
            "Initialized",
        )
        self.call("Renew", "<wsnt:TerminationTime>PT120S</wsnt:TerminationTime>", key)
        self.call("Unsubscribe", key=key)
        with self.assertRaises(ValueError):
            self.call("PullMessages", key=key)

    def test_properties_are_parseable_and_no_fake_observation(self):
        response = self.call("GetEventProperties")
        self.assertIsNotNone(
            response.find(".//tns1:VideoSource/tns1:MotionAlarm", NAMESPACES)
        )
        self.assertIsNotNone(
            response.find(".//tns1:Device/tns1:Trigger/tns1:Alarm", NAMESPACES)
        )
        self.call("GetServiceCapabilities")
        key = (
            self.call("CreatePullPointSubscription")
            .find(".//wsa:Address", NAMESPACES)
            .text.rsplit("/", 1)[-1]
        )
        self.call("SetSynchronizationPoint", key=key)
        self.assertIsNone(
            self.call("PullMessages", key=key).find(
                "wsnt:NotificationMessage", NAMESPACES
            )
        )

    def test_rejects_unsupported_filter(self):
        with self.assertRaises(ValueError):
            self.call(
                "CreatePullPointSubscription",
                '<wsnt:Filter><wsnt:MessageContent Dialect="xpath">//foo</wsnt:MessageContent></wsnt:Filter>',
            )
        response = self.call(
            "CreatePullPointSubscription",
            f'<wsnt:Filter><wsnt:TopicExpression Dialect="{DIALECT}">{TOPICS[0]}</wsnt:TopicExpression></wsnt:Filter>',
        )
        self.assertIsNotNone(response.find(".//wsa:Address", NAMESPACES))


if __name__ == "__main__":
    unittest.main()


class EventSchemaTests(unittest.TestCase):
    def test_event_property_elements_use_ws_notification_namespaces(self):
        broker = EventBroker()

        class Registry:
            events = broker

        response = ET.Element("{" + NAMESPACES["tev"] + "}GetEventPropertiesResponse")
        handle_events(
            response,
            "GetEventProperties",
            {"export_id": "sample"},
            ET.Element("request"),
            Registry(),
        )
        tags = [node.tag for node in response]
        self.assertIn("{" + NAMESPACES["wsnt"] + "}FixedTopicSet", tags)
        self.assertIn("{" + NAMESPACES["wsnt"] + "}TopicExpressionDialect", tags)
        self.assertIn("{" + NAMESPACES["tev"] + "}MessageContentFilterDialect", tags)
