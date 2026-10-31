"""Bounded ONVIF pan/tilt using the existing serialized native camera driver."""

import math
import threading
import time


class MotionController:
    def __init__(self, camera):
        self.camera = camera
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None

    def _confirmed(self, action, args=None):
        camera = self.camera()
        if camera is None:
            raise ValueError("camera_not_streaming")
        result = camera.control(action, args or {})
        if result.get("state") not in ("confirmed", "sent"):
            raise ValueError("camera_command_rejected")
        return result

    def moving(self):
        return bool(
            self.thread and self.thread.is_alive() and not self.stop_event.is_set()
        )

    def move(self, lens, x, y, timeout):
        if (
            type(lens) is not int
            or not 0 <= lens <= 15
            or not all(
                isinstance(v, (int, float)) and math.isfinite(v)
                for v in (x, y, timeout)
            )
            or abs(x) > 1
            or abs(y) > 1
            or not 0.08 <= timeout <= 5
        ):
            raise ValueError("invalid_velocity")
        with self.lock:
            # Stop and replace are one transaction: concurrent clients must
            # never leave an older worker running after its reference is lost.
            self.stop()
            if not x and not y:
                return
            self.stop_event = threading.Event()
            stop = self.stop_event
            self.thread = threading.Thread(
                target=self._run, args=(stop, lens, x, y, timeout), daemon=True
            )
            self.thread.start()

    def _run(self, stop, lens, x, y, timeout):
        end = time.monotonic() + timeout
        try:
            while not stop.is_set() and time.monotonic() < end:
                for value, negative, positive in [
                    (x, "left", "right"),
                    (y, "down", "up"),
                ]:
                    if not value or stop.is_set() or time.monotonic() >= end:
                        continue
                    pulse = max(80, min(250, int((end - time.monotonic()) * 1000)))
                    started = time.monotonic()
                    self._confirmed(
                        "ptz",
                        {
                            "direction": positive if value > 0 else negative,
                            "duration_ms": pulse,
                            "speed": max(1, min(10, round(abs(value) * 10))),
                            "lens": lens,
                        },
                    )
                    stop.wait(max(0, pulse / 1000 - (time.monotonic() - started)))
        except (ValueError, OSError):
            pass
        finally:
            try:
                self._confirmed("ptz_stop")
            except (ValueError, OSError):
                pass

    def stop(self, force=False):
        with self.lock:
            self.stop_event.set()
            thread = self.thread
            if thread and thread is not threading.current_thread():
                thread.join(timeout=13)
                if thread.is_alive():
                    raise ValueError("ptz_stop_pending")
            if (thread or force) and self.camera():
                self._confirmed("ptz_stop")

    def preset(self, operation, slot, name=None):
        camera = self.camera()
        if not camera:
            raise ValueError("camera_not_streaming")
        if operation == "get_presets":
            reply = camera.control("query", {"section": "status"})
            value = reply.get("parameters", {}).get("preset_value")
            if value is None:
                raise ValueError("preset_state_unknown")
            try:
                mask = int(value)
            except (ValueError, TypeError):
                raise ValueError("preset_state_unknown") from None
            return [
                {"slot": n, "name": "Preset " + str(n)}
                for n in range(1, 6)
                if mask & (1 << (n - 1))
            ]
        if operation == "set_preset" and slot is None:
            existing = {p["slot"] for p in self.preset("get_presets", None)}
            slot = next((n for n in range(1, 6) if n not in existing), None)
        if type(slot) is not int or not 1 <= slot <= 5:
            raise ValueError("invalid_preset")
        mode = {
            "set_preset": "save",
            "goto_preset": "goto",
            "remove_preset": "delete",
        }.get(operation)
        if not mode:
            raise ValueError("unsupported_preset_operation")
        result = camera.control("preset", {"operation": mode, "slot": slot})
        if result.get("state") != "confirmed":
            raise ValueError("preset_not_confirmed")
        return {"slot": slot}
