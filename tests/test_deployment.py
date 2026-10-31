import os
import shutil
from pathlib import Path
import subprocess
import unittest


@unittest.skipUnless(
    shutil.which("docker"), "Docker Compose is optional for native Python tests"
)
class DeploymentTests(unittest.TestCase):
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
        self.assertNotIn("ports", services["bridge"])
        self.assertEqual(services["web"]["environment"]["BRIDGE_HOST"], "bridge")
        self.assertEqual(services["web"]["ports"][0]["target"], 8080)
