import os
import shutil
from pathlib import Path
import subprocess
import unittest


@unittest.skipUnless(
    shutil.which("docker"), "Docker Compose is optional for native Python tests"
)
class DeploymentTests(unittest.TestCase):
    def test_clean_compose_needs_no_client_file_and_serves_lan_dashboard(self):
        import json

        env = dict(os.environ)
        env.pop("WEB_LISTEN", None)
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                "/dev/null",
                "-f",
                "compose.yaml",
                "config",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertEqual(services["web"]["environment"]["WEB_LISTEN"], "0.0.0.0")
        bridge = services["bridge"]
        self.assertNotIn("BRIDGE_CREDENTIAL_CLIENT", bridge["environment"])
        self.assertFalse(
            any("credentials" in volume["target"] for volume in bridge["volumes"])
        )
        self.assertIn("127.0.0.1", bridge["command"])

    def test_desktop_profile_publishes_web_but_keeps_api_internal(self):
        import json

        env = dict(os.environ, COMPOSE_FILE="compose.yaml:compose.desktop.yaml")
        result = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertNotIn("network_mode", services["bridge"])
        self.assertTrue(
            all(port["target"] != 8098 for port in services["bridge"].get("ports", []))
        )
        self.assertEqual(services["web"]["environment"]["BRIDGE_HOST"], "bridge")
        self.assertEqual(services["web"]["ports"][0]["target"], 8080)

    def test_linux_exports_honor_explicit_listener_restrictions(self):
        import json

        env = dict(os.environ, RTSP_LISTEN="127.0.0.1", ONVIF_LISTEN="127.0.0.1")
        result = subprocess.run(
            ["docker", "compose", "-f", "compose.yaml", "config", "--format", "json"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertEqual(
            services["mediamtx"]["environment"]["MTX_RTSPADDRESS"], "127.0.0.1:8554"
        )
        self.assertEqual(
            services["bridge"]["environment"]["BRIDGE_ONVIF_LISTEN"], "127.0.0.1"
        )
