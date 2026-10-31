import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from okam_bridge.__main__ import read_access_token


class CLITokenTests(unittest.TestCase):
    def test_private_gateway_token_can_be_loaded_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "gateway"
            p.write_text("a-long-random-token-for-test\n")
            self.assertEqual(
                read_access_token("UNSET_TEST_TOKEN", str(p)),
                "a-long-random-token-for-test",
            )

    def test_empty_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "gateway"
            p.write_text("")
            with self.assertRaises(ValueError):
                read_access_token("UNSET_TEST_TOKEN", str(p))
