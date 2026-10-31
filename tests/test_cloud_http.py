import json
import time
import unittest
from unittest.mock import Mock

import test_account_http as fixture


class CloudHTTPTests(unittest.TestCase):
    def setUp(self):
        self.http = fixture.AccountHTTPTests()
        self.http.setUp()
        self.addCleanup(self.http.tearDown)

    def test_connect_mode_is_validated_and_cloud_works_without_ip(self):
        cookie = self.http.login("first")
        workspace = self.http.manager.get(cookie.split("=", 1)[1])
        cid = next(iter(workspace.records))
        route = "/api/cameras/" + cid + "/connect"
        workspace.backend.prepare = Mock(return_value={"id": cid, "name": "Fixture"})
        self.assertEqual(
            self.http.request(route, "POST", {"connection_mode": "bad"}, cookie)[0], 400
        )
        workspace.backend.prepare.assert_not_called()
        self.assertEqual(
            self.http.request(route, "POST", {"connection_mode": "cloud"}, cookie)[0],
            202,
        )
        for _ in range(100):
            if cid in workspace.cameras:
                break
            time.sleep(0.01)
        camera = json.loads(self.http.request("/api/cameras/" + cid, cookie=cookie)[2])
        self.assertTrue(camera["viewable"])
        self.assertEqual(camera["connection_mode"], "cloud")
        self.assertIsNone(camera["ip"])
        self.assertEqual(workspace.cameras[cid].config["connection_mode"], "cloud")
