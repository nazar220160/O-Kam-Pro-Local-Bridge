"""Parse facade replies using independent, packaged ONVIF WSDL schemas."""

import unittest
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

try:
    import onvif
    from lxml import etree
    from zeep import Client
except ImportError:
    onvif = None

from okam_bridge.onvif_events import EventBroker, NAMESPACES, handle_events
from okam_bridge.onvif_archive import ArchiveSearch, handle_archive


@unittest.skipUnless(onvif, "Install requirements-dev.txt for ONVIF WSDL validation")
class WSDLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(onvif.__file__).resolve().parent.parent / "wsdl"
        cls.clients = {
            name: Client(str(root / (name + ".wsdl")))
            for name in ("events", "recording", "search", "replay")
        }

    def parse(self, service, node):
        client = self.clients[service]
        return client.get_element(node.tag).parse(
            etree.fromstring(ET.tostring(node)), client.wsdl.types
        )

    def test_event_properties_subscription_and_actual_notification(self):
        registry = SimpleNamespace(events=EventBroker())
        item = dict(export_id="fixture", advertise_host="127.0.0.1", onvif_port=8899)

        def call(action, content="", subscription=None):
            request = ET.fromstring("<request>" + content + "</request>")
            response = ET.Element("{" + NAMESPACES["tev"] + "}" + action + "Response")
            handle_events(response, action, item, request, registry, subscription)
            return self.parse("events", response)

        props = call("GetEventProperties")
        self.assertTrue(props.FixedTopicSet)
        self.assertEqual(
            props.TopicExpressionDialect,
            ["http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet"],
        )
        created = call("CreatePullPointSubscription")
        self.assertIn("/subscriptions/", created.SubscriptionReference.Address._value_1)
        key = registry.events.subscribe("fixture")
        registry.events.publish(
            "fixture",
            "tns1:Device/Trigger/Alarm",
            {"rawAlarm": "alarm_status"},
            {"State": "0"},
        )
        result = call(
            "PullMessages",
            "<Timeout>PT0S</Timeout><MessageLimit>10</MessageLimit>",
            key,
        )
        self.assertEqual(len(result.NotificationMessage), 1)

    def test_recording_search_and_replay_responses(self):
        row = dict(
            token="fixture",
            source="sd",
            lens=0,
            start="2026-01-01T00:00:00Z",
            end="2026-01-01T00:01:00Z",
        )
        registry = SimpleNamespace(
            searches=ArchiveSearch(),
            archive_records=lambda eid: [row],
            archive_replay=lambda eid, token: "rtsp://127.0.0.1:8554/fixture/replay/fixture",
        )
        item = dict(export_id="fixture", name="Fixture", recording=True)

        def call(service, action, content=""):
            ns = "http://www.onvif.org/ver10/" + service + "/wsdl"
            response = ET.Element("{" + ns + "}" + action + "Response")
            handle_archive(
                response,
                service,
                action,
                item,
                ET.fromstring("<request>" + content + "</request>"),
                registry,
            )
            return self.parse(service, response)

        records = call("recording", "GetRecordings")
        self.assertEqual(records.RecordingItem[0].RecordingToken, "fixture")
        summary = call("search", "GetRecordingSummary")
        self.assertEqual(summary.Summary.NumberRecordings, 1)
        token = call(
            "search", "FindRecordings", "<Scope/><KeepAliveTime>PT60S</KeepAliveTime>"
        ).SearchToken
        results = call(
            "search",
            "GetRecordingSearchResults",
            "<SearchToken>" + token + "</SearchToken>",
        )
        self.assertEqual(
            results.ResultList.RecordingInformation[0].RecordingToken, "fixture"
        )
        replay = call(
            "replay",
            "GetReplayUri",
            "<RecordingToken>fixture</RecordingToken><StreamSetup><Stream>RTP-Unicast</Stream><Transport><Protocol>RTSP</Protocol></Transport></StreamSetup>",
        )
        self.assertTrue(replay.Uri.startswith("rtsp://"))
