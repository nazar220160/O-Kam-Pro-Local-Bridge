import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class MacOSLauncherTests(unittest.TestCase):
    def launcher(self):
        path = Path("scripts/native_host.py")
        spec = importlib.util.spec_from_file_location("native_host", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_command_keeps_api_loopback_and_requires_private_gateway(self):
        with tempfile.TemporaryDirectory() as root:
            command = self.launcher().native_command(Path(root), "/custom/python", 8098)
            self.assertEqual(
                command[:4], ["/custom/python", "-m", "okam_bridge", "api"]
            )
            self.assertEqual(command[command.index("--listen") + 1], "127.0.0.1")
            self.assertIn("--access-token-file", command)
            self.assertNotIn("--credential-client", command)
            Path(root, "secrets").mkdir()
            Path(root, "secrets/SuperIPCam.exe").touch()
            command = self.launcher().native_command(Path(root), "/custom/python", 8098)
            self.assertIn("--credential-client", command)

    def test_gateway_token_is_private_to_project_and_stable_across_restarts(self):
        module = self.launcher()
        with tempfile.TemporaryDirectory() as root:
            path = module.prepare_runtime(Path(root))
            token = path.read_text()
            self.assertGreaterEqual(len(token), 32)
            self.assertEqual(path, module.prepare_runtime(Path(root)))
            self.assertEqual(path.read_text(), token)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_child_cannot_override_gateway_token_from_unrelated_shell_settings(self):
        with patch.dict(
            os.environ,
            {
                "BRIDGE_ACCESS_TOKEN": "another-project-token",
                "BRIDGE_ACCESS_TOKEN_FILE": "/another/project/token",
            },
        ):
            env = self.launcher().native_environment()
        self.assertNotIn("BRIDGE_ACCESS_TOKEN", env)
        self.assertNotIn("BRIDGE_ACCESS_TOKEN_FILE", env)
        self.assertIn("PATH", env)

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose is optional")
    def test_macos_profile_uses_native_api_not_docker_udp(self):
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "compose.yaml",
                "-f",
                "compose.macos.yaml",
                "config",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertEqual(
            services["web"]["environment"]["BRIDGE_HOST"], "host.docker.internal"
        )
        self.assertFalse(services["web"].get("depends_on"))
        self.assertNotIn("bridge", services)
        self.assertEqual(services["web"]["ports"][0]["host_ip"], "127.0.0.1")
