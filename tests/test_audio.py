import unittest
from unittest.mock import patch
from okam_bridge.transport import start_audio, read_lens_frame
from okam_bridge.exports import publisher_command
from okam_bridge.camera import Camera
from test_lenses import BufferedSession


class AudioTests(unittest.TestCase):
    def test_native_audio_start_uses_separate_ack_and_no_persistent_write(self):
        with patch("okam_bridge.transport.write_command") as write, patch(
            "okam_bridge.transport.read_reply", return_value=(0x6031, 0)
        ) as reply:
            start_audio(object(), "admin", "synthetic")
        self.assertIn(b"audiostream.cgi?streamid=7&", write.call_args.args[1])
        self.assertEqual(reply.call_args.args[1], (0x6031,))

    def test_audio_frame_is_read_without_video_parsing(self):
        header = bytearray(32)
        header[:4] = bytes.fromhex("55aa15a8")
        header[4] = 12
        header[16:20] = (160).to_bytes(4, "little")
        data, kind, lens = read_lens_frame(
            BufferedSession(header + bytes([0xD5]) * 160)
        )
        self.assertEqual((kind, lens, len(data)), (12, 0, 160))

    def test_publisher_maps_observed_audio_to_aac_without_reencoding_video(self):
        command = publisher_command("ffmpeg", "rtsp://example/stream", 10, 7)
        self.assertIn("alaw", command)
        self.assertIn("pipe:7", command)
        self.assertEqual(command[command.index("-c:a") + 1], "aac")
        self.assertEqual(command[command.index("-c:v") + 1], "copy")
        self.assertNotIn("-an", command)
        self.assertIn("-an", publisher_command("ffmpeg", "rtsp://example/stream"))

    def test_camera_audio_starts_unavailable_and_cancellation_is_bounded(self):
        camera = Camera({"id": "fixture"}, "ffmpeg")
        self.assertFalse(camera.status()["audio"]["available"])
        import threading

        cancel = threading.Event()
        cancel.set()
        with patch.object(camera, "_run"):
            self.assertEqual(list(camera.frames("audio", cancel=cancel)), [])
        camera.stop()

    def test_real_ffmpeg_mux_and_decode_video_with_camera_alaw_audio(self):
        import os, shutil, subprocess, tempfile, threading, json
        from pathlib import Path

        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            self.skipTest("FFmpeg required")
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "video.h264"
            output = Path(directory) / "av.mkv"
            subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=s=64x64:r=10",
                    "-t",
                    "2",
                    "-c:v",
                    "libx264",
                    "-f",
                    "h264",
                    str(raw),
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
            read, write = os.pipe()
            command = publisher_command(ffmpeg, "unused", 10, read)
            command = command[:-9] + ["-f", "matroska", str(output)]
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                pass_fds=(read,),
            )
            os.close(read)

            def audio():
                try:
                    data = memoryview(bytes([0xD5]) * 16000)
                    while data:
                        data = data[os.write(write, data) :]
                finally:
                    os.close(write)

            thread = threading.Thread(target=audio)
            thread.start()
            try:
                _, error = process.communicate(raw.read_bytes(), timeout=15)
                self.assertEqual(process.returncode, 0, error.decode())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                thread.join(3)
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_streams", "-of", "json", str(output)],
                check=True,
                capture_output=True,
                timeout=5,
            )
            codecs = {s["codec_name"] for s in json.loads(result.stdout)["streams"]}
            self.assertEqual(codecs, {"h264", "aac"})
            subprocess.run(
                [ffmpeg, "-v", "error", "-i", str(output), "-f", "null", "-"],
                check=True,
                capture_output=True,
                timeout=10,
            )
