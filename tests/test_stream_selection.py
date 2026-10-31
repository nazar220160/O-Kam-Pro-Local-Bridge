import unittest
from unittest.mock import patch
from urllib.parse import parse_qs
from okam_bridge.transport import start_video


class StreamSelectionTests(unittest.TestCase):
    def test_each_supported_profile_is_sent_to_camera_without_losing_account(self):
        for profile in (0, 1, 2):
            with self.subTest(profile=profile):
                sent = []
                with patch(
                    "okam_bridge.transport.write_command",
                    side_effect=lambda s, r: sent.append(r),
                ), patch("okam_bridge.transport.read_reply", return_value=(0x6001, 0)):
                    start_video(
                        object(), "admin", "native", profile, "888888", account_id="123"
                    )
                q = parse_qs(sent[0][8:].decode().split("?", 1)[1])
                self.assertEqual(q["substream"], [str(profile)])
                self.assertEqual(q["userId"], ["123"])
