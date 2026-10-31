import threading, time, unittest
from okam_bridge.export_motion import MotionController


class Camera:
    def __init__(self):
        self.calls = []

    def control(self, action, args=None):
        self.calls.append((action, args))
        return {"state": "confirmed", "result": 0, "parameters": {"preset_value": 1}}


class MotionTests(unittest.TestCase):
    def test_continuous_move_is_bounded_and_stop_waits_for_current_pulse(self):
        camera = Camera()
        motion = MotionController(lambda: camera)
        motion.move(0, 0.5, 0, 0.1)
        time.sleep(0.18)
        motion.stop()
        moves = [c for c in camera.calls if c[0] == "ptz"]
        self.assertTrue(moves)
        self.assertEqual(moves[0][1]["direction"], "right")
        self.assertEqual(camera.calls[-1][0], "ptz_stop")
        self.assertFalse(motion.moving())

    def test_invalid_velocity_never_moves(self):
        c = Camera()
        m = MotionController(lambda: c)
        for x in [float("nan"), float("inf"), 2]:
            with self.assertRaises(ValueError):
                m.move(0, x, 0, 1)
        self.assertEqual(c.calls, [])

    def test_preset_requires_firmware_confirmation(self):
        c = Camera()
        m = MotionController(lambda: c)
        self.assertEqual(
            m.preset("get_presets", None), [{"slot": 1, "name": "Preset 1"}]
        )
        self.assertEqual(m.preset("set_preset", None)["slot"], 2)
        self.assertEqual(c.calls[-1], ("preset", {"operation": "save", "slot": 2}))

    def test_concurrent_moves_cannot_create_untracked_motion_worker(self):
        from unittest.mock import patch

        camera = Camera()
        motion = MotionController(lambda: camera)
        entered, release, second_done = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        original_stop = motion.stop

        def delayed_stop(*args, **kwargs):
            original_stop(*args, **kwargs)
            if threading.current_thread().name == "first-move":
                entered.set()
                release.wait(2)

        def second_move():
            motion.move(0, -0.5, 0, 0.1)
            second_done.set()

        first = threading.Thread(
            target=lambda: motion.move(0, 0.5, 0, 0.1), name="first-move"
        )
        second = threading.Thread(target=second_move)
        try:
            with patch.object(motion, "stop", side_effect=delayed_stop):
                first.start()
                self.assertTrue(entered.wait(1))
                second.start()
                try:
                    self.assertFalse(
                        second_done.wait(0.05),
                        "second move must wait for first stop/start transaction",
                    )
                finally:
                    release.set()
                    first.join(2)
                    second.join(2)
        finally:
            original_stop()
        self.assertFalse(motion.moving())
