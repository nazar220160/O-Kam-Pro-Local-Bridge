import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch

from okam_bridge.onvif_archive import ArchiveSearch, NAMESPACES, handle_archive


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.searches = ArchiveSearch()
        self.rows = [dict(token=str(i), end="2026-01-01T01:00:00Z") for i in range(250)]

    def test_paging_scope_and_drop(self):
        token = self.searches.create("a", self.rows)
        with self.assertRaises(ValueError):
            self.searches.results("b", token)
        self.assertEqual(len(self.searches.results("a", token, 1000)), 100)
        self.assertEqual(len(self.searches.results("a", token)), 100)
        self.assertEqual(len(self.searches.results("a", token)), 50)
        self.assertEqual(self.searches.state("a", token), "Completed")
        self.searches.drop("a")
        with self.assertRaises(ValueError):
            self.searches.state("a", token)

    def test_expiration_snapshot_and_limit(self):
        with patch("okam_bridge.onvif_archive.time.monotonic", return_value=1):
            token = self.searches.create("a", self.rows, ttl=2, max_matches=1)
        self.rows[0]["token"] = "changed"
        with patch("okam_bridge.onvif_archive.time.monotonic", return_value=2):
            self.assertEqual(self.searches.results("a", token)[0]["token"], "0")
        with patch("okam_bridge.onvif_archive.time.monotonic", return_value=5):
            with self.assertRaises(ValueError):
                self.searches.state("a", token)
        for _ in range(32):
            self.searches.create("a", [])
        with self.assertRaises(ValueError):
            self.searches.create("a", [])

    def test_removed_clips_filtered_and_end_revokes(self):
        token = self.searches.create("a", self.rows)
        self.assertEqual(
            self.searches.results("a", token, valid_tokens={"1"})[0]["token"], "1"
        )
        self.assertEqual(self.searches.end("a", token), "2026-01-01T01:00:00Z")
        with self.assertRaises(ValueError):
            self.searches.end("a", token)


class ArchiveSOAPTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            dict(
                token="clip1",
                source="sd",
                lens=1,
                start="2026-01-01T00:00:00Z",
                end="2026-01-01T00:01:00Z",
                duration=60,
                size=1024,
                path="/private/hidden",
            )
        ]
        self.registry = SimpleNamespace(
            searches=ArchiveSearch(),
            archive_records=lambda export_id: self.rows if export_id == "a" else [],
            archive_replay=lambda export_id, token: "rtsp://127.0.0.1:8554/archive/a/clip1",
        )
        self.item = dict(export_id="a", name="Garden", recording=True)

    def call(self, service, action, content="", item=None):
        prefix = {"recording": "trc", "search": "tse", "replay": "trp"}[service]
        request = ET.fromstring(
            f'<{prefix}:{action} xmlns:{prefix}="{NAMESPACES[prefix]}" xmlns:tt="{NAMESPACES["tt"]}">{content}</{prefix}:{action}>'
        )
        response = ET.Element("{" + NAMESPACES[prefix] + "}" + action + "Response")
        handle_archive(
            response,
            service + "_service",
            action,
            item or self.item,
            request,
            self.registry,
        )
        serialized = ET.tostring(response)
        self.assertNotIn(b"/private", serialized)
        return ET.fromstring(serialized)

    def names(self, node):
        return [child.tag.split("}")[-1] for child in node]

    def test_recording_wsdl_shapes_and_track_configuration(self):
        response = self.call("recording", "GetRecordings")
        recording = response.find("trc:RecordingItem", NAMESPACES)
        self.assertEqual(
            self.names(recording), ["RecordingToken", "Configuration", "Tracks"]
        )
        config = recording.find("tt:Configuration", NAMESPACES)
        self.assertEqual(
            self.names(config), ["Source", "Content", "MaximumRetentionTime"]
        )
        self.assertEqual(
            self.names(config.find("tt:Source", NAMESPACES)),
            ["SourceId", "Name", "Location", "Description", "Address"],
        )
        self.assertEqual(
            config.find("tt:Source/tt:Description", NAMESPACES).text,
            "sd recording, lens 1",
        )
        content = "<trc:RecordingToken>clip1</trc:RecordingToken>"
        self.call("recording", "GetRecordingConfiguration", content)
        response = self.call(
            "recording",
            "GetTrackConfiguration",
            content + "<trc:TrackToken>video</trc:TrackToken>",
        )
        self.assertEqual(
            response.find("trc:TrackConfiguration/tt:TrackType", NAMESPACES).text,
            "Video",
        )
        with self.assertRaises(ValueError):
            self.call(
                "recording",
                "GetTrackConfiguration",
                content + "<trc:TrackToken>audio</trc:TrackToken>",
            )
        with self.assertRaises(ValueError):
            self.call("recording", "DeleteRecording", content)

    def test_search_information_wsdl_order(self):
        response = self.call(
            "search",
            "GetRecordingInformation",
            "<tse:RecordingToken>clip1</tse:RecordingToken>",
        )
        info = response.find("tse:RecordingInformation", NAMESPACES)
        self.assertEqual(
            self.names(info),
            [
                "RecordingToken",
                "Source",
                "EarliestRecording",
                "LatestRecording",
                "Content",
                "Track",
                "RecordingStatus",
            ],
        )
        self.assertEqual(info.find("tt:RecordingStatus", NAMESPACES).text, "Stopped")
        summary = self.call("search", "GetRecordingSummary").find(
            "tse:Summary", NAMESPACES
        )
        self.assertEqual(
            self.names(summary), ["DataFrom", "DataUntil", "NumberRecordings"]
        )
        self.assertEqual(summary.find("tt:NumberRecordings", NAMESPACES).text, "1")

    def test_search_round_trip_and_export_isolation(self):
        response = self.call(
            "search",
            "FindRecordings",
            "<tse:Scope><tt:IncludedRecordings>clip1</tt:IncludedRecordings></tse:Scope><tse:KeepAliveTime>PT30S</tse:KeepAliveTime>",
        )
        token = response.find("tse:SearchToken", NAMESPACES).text
        content = f"<tse:SearchToken>{token}</tse:SearchToken>"
        other = dict(self.item, export_id="b")
        with self.assertRaises(ValueError):
            self.call("search", "GetRecordingSearchResults", content, item=other)
        result = self.call("search", "GetRecordingSearchResults", content)
        self.assertEqual(
            len(result.findall("tse:ResultList/tt:RecordingInformation", NAMESPACES)), 1
        )
        self.assertEqual(
            self.call("search", "GetSearchState", content)
            .find("tse:State", NAMESPACES)
            .text,
            "Completed",
        )
        self.call("search", "EndSearch", content)
        with self.assertRaises(ValueError):
            self.call("search", "GetSearchState", content)
        with self.assertRaises(ValueError):
            self.call(
                "search",
                "FindRecordings",
                "<tse:Scope><tt:RecordingInformationFilter>//foo</tt:RecordingInformationFilter></tse:Scope>",
            )

    def test_replay_only_real_normal_forward_uri(self):
        setup = "<trp:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream><tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trp:StreamSetup>"
        content = setup + "<trp:RecordingToken>clip1</trp:RecordingToken>"
        uri = (
            self.call("replay", "GetReplayUri", content)
            .find("trp:Uri", NAMESPACES)
            .text
        )
        self.assertEqual(uri, "rtsp://127.0.0.1:8554/archive/a/clip1")
        caps = self.call("replay", "GetServiceCapabilities").find(
            "trp:Capabilities", NAMESPACES
        )
        self.assertEqual(caps.get("ReversePlayback"), "false")
        for action, body in [
            ("GetReplayUri", content.replace("clip1", "unknown")),
            ("GetReplayUri", content.replace("RTSP", "UDP")),
            ("GetReplayUri", "<trp:RecordingToken>clip1</trp:RecordingToken>"),
            ("SetReplayConfiguration", ""),
        ]:
            with self.assertRaises(ValueError):
                self.call("replay", action, body)
        self.registry.archive_replay = (
            lambda *args: "rtsp://user:secret@127.0.0.1/private"
        )
        with self.assertRaises(ValueError):
            self.call("replay", "GetReplayUri", content)
        with self.assertRaises(ValueError):
            self.call(
                "search",
                "GetRecordingInformation",
                "<tse:RecordingToken>unknown</tse:RecordingToken>",
            )

    def test_empty_archive_never_fabricates_recordings(self):
        self.rows.clear()
        self.assertEqual(list(self.call("recording", "GetRecordings")), [])
        summary = self.call("search", "GetRecordingSummary")
        self.assertEqual(summary.find(".//tt:NumberRecordings", NAMESPACES).text, "0")


if __name__ == "__main__":
    unittest.main()
