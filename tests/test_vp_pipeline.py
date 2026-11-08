import unittest
from unittest.mock import Mock, patch

from okam_bridge.camera import Camera
from okam_bridge.controls import ControlError, build_action, execute_action
from okam_bridge.transport import CS2Error


class VPPipelineTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "id": "fixture",
            "name": "Camera",
            "protocol": "vp",
            "connection_mode": "cloud",
            "substream": 0,
            "quality": "low",
        }
        self.camera = Camera(self.config, "ffmpeg")
        self.session = Mock(protocol="vp", connect_path="relay-tcp")
        self.session.authenticate.return_value = ("admin", "camera-secret")
        self.session.camera_metadata = {"audio_g711": True, "microphone": True}
        self.session.last_control_payload = b"result=0;"
        self.session.last_video_header = bytes(32)

    def test_optional_quality_failure_and_unverified_audio_do_not_block_video(self):
        # Subscribe only to lens 2. The session still sees every native frame.
        sub = self.camera._media(2).hubs["h264"].subscribe()
        video = b"\x00\x00\x01\x41\x80"
        frames = iter([(b"audio", 12, 0), (video, 1, 2)])

        def read_frame(*, timeout):
            frame = next(frames)
            if frame[2] == 2:
                self.camera.stop_event.set()
            return frame

        self.session.read_lens_frame.side_effect = read_frame
        self.session.request.side_effect = CS2Error("quality unavailable")
        with patch(
            "okam_bridge.transport.connect_vp", return_value=self.session
        ) as connect:
            self.camera._run()

        connect.assert_called_once_with(self.config, cancel=self.camera.stop_event)
        self.session.authenticate.assert_called_once_with()
        self.session.authorize_account.assert_called_once_with()
        self.session.start_video.assert_called_once_with(0)
        self.session.request.assert_called_once_with(
            "camera_control.cgi?param=16&value=4&", timeout=2
        )
        self.session.close.assert_called_once_with()
        self.assertEqual(sub.get(0), video)
        status = self.camera.status()
        self.assertEqual(status["protocol"], "VP/CPPPP2")
        self.assertIn(2, status["lenses"])
        self.assertEqual(status["audio"]["frames_received"], 0)

    def test_quality_uses_vp_requests_and_ptz_is_rejected_before_queueing(self):
        self.session.read_control.side_effect = [None, (0x6012, b"result=0;")]
        result = execute_action(
            self.session, self.config, build_action("quality", {"quality": "high"})
        )
        self.assertEqual(result["state"], "confirmed")
        self.session.request.assert_called_once_with(
            "camera_control.cgi?param=16&value=1&", timeout=1
        )

        self.camera.session = self.session
        self.camera.state = "streaming"
        with self.assertRaisesRegex(ControlError, "vp_control_unsupported"):
            self.camera.control("ptz_step", {"direction": "left"})
        self.assertTrue(self.camera.control_queue.empty())
