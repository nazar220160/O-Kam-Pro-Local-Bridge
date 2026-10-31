import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from test_bridge import ENTRY


class ShutdownTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX SIGTERM lifecycle")
    def test_sigterm_stops_server_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text(
                json.dumps(
                    {
                        "port": 0,
                        "cameras": [dict(ENTRY, password="test-only", password_env="")],
                    }
                )
            )
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    "-m",
                    "okam_bridge",
                    "serve",
                    "--config",
                    str(p),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                ready = child.stdout.readline()
                self.assertIn("http://127.0.0.1:", ready)
                child.send_signal(signal.SIGTERM)
                self.assertEqual(child.wait(timeout=5), 0)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                child.stdout.close()
                child.stderr.close()
