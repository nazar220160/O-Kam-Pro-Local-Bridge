import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_export_http as helpers
from okam_bridge.archive import ArchiveManager
from okam_bridge.vendor.cs2 import CS2Error


class ArchiveHTTPTests(unittest.TestCase):
    req = helpers.ExportHTTPTests.req
    login = helpers.ExportHTTPTests.login

    def setUp(self):
        helpers.ExportHTTPTests.setUp(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.server.exports.archive = ArchiveManager(self.server.exports, self.tmp.name)

    def tearDown(self):
        helpers.ExportHTTPTests.tearDown(self)
        self.tmp.cleanup()

    def record(self, workspace, cid):
        store = self.server.exports.archive.store
        path = store.directory(workspace.account_id, cid) / "fixture.mkv"
        path.write_bytes(b"0123456789abcdef")
        with patch.object(store, "probe", return_value=1):
            return store.add_recording(
                workspace.account_id, cid, path, start="2026-01-01T00:00:00Z"
            )

    def test_download_requires_account_scope_and_supports_bounded_ranges(self):
        cookie, workspace, cid = self.login("first")
        row = self.record(workspace, cid)
        route = "/api/cameras/" + cid + "/archive/file/" + row["token"]
        self.assertEqual(self.req(route)[0], 401)
        auth = (
            "Basic "
            + base64.b64encode(("player:" + workspace.player_token).encode()).decode()
        )
        self.assertEqual(self.req(route, headers={"Authorization": auth})[0], 401)
        other, other_workspace, _ = self.login("second")
        other_workspace.account_id = "different-account"
        self.assertEqual(self.req(route, cookie=other)[0], 404)
        code, headers, data = self.req(
            route, cookie=cookie, headers={"Range": "bytes=3-7"}
        )
        self.assertEqual((code, data), (206, b"34567"))
        self.assertEqual(headers["Content-Range"], "bytes 3-7/16")
        self.assertEqual(
            self.req(route, cookie=cookie, headers={"Range": "bytes=99-"})[0], 416
        )
        self.assertEqual(
            self.req(route, cookie=cookie, headers={"Range": "bytes=0-1,4-5"})[0], 416
        )
        self.assertEqual(self.req(route, cookie=cookie)[2], b"0123456789abcdef")
        status = self.req("/api/cameras/" + cid + "/archive", cookie=cookie)
        self.assertNotIn(self.tmp.name.encode(), status[2])
        self.assertNotIn(b"path", status[2])

    def test_sd_transport_failure_is_safe_json_and_does_not_reset_connection(self):
        cookie, _, cid = self.login("first")
        with patch.object(
            self.server.exports.archive,
            "sd_dates",
            side_effect=CS2Error("private-native-details"),
        ):
            code, _, data = self.req(
                "/api/cameras/" + cid + "/archive/sd_dates", cookie=cookie
            )
        self.assertEqual(code, 400)
        self.assertEqual(json.loads(data), {"error": "sd_archive_unavailable"})
