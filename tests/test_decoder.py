import shutil
import subprocess
import threading
import time
import unittest
from okam_bridge.camera import JPEGDecoder


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is needed for decoder integration")
class DecoderTests(unittest.TestCase):
    def test_real_h264_decodes_to_jpeg_and_stops(self):
        ff = shutil.which("ffmpeg")
        clip = subprocess.run(
            [
                ff,
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=160x90:rate=15",
                "-t",
                "3",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-tune",
                "zerolatency",
                "-g",
                "10",
                "-f",
                "h264",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
        ).stdout
        ready = threading.Event()
        frames = []

        def receive(frame):
            frames.append(frame)
            ready.set()

        d = JPEGDecoder(ff, receive)
        try:
            d.write(clip)
            d.process.stdin.close()
            self.assertTrue(ready.wait(5), "FFmpeg did not produce a JPEG")
            self.assertTrue(frames[0].startswith(b"\xff\xd8"))
            self.assertTrue(frames[0].endswith(b"\xff\xd9"))
        finally:
            d.close()
            d.close()
        self.assertFalse(d.thread.is_alive())
        self.assertIsNotNone(d.process.poll())
