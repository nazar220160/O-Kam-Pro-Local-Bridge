import unittest, threading, time, struct
from unittest.mock import patch
from okam_bridge.controls import (
    build_action,
    ControlError,
    parse_variables,
    public_fields,
    execute_action,
    ControlJob,
)


class ControlTests(unittest.TestCase):
    def test_ptz_has_verified_direction_stop_and_bounded_duration(self):
        for direction, command in [("up", 0), ("down", 2), ("left", 4), ("right", 6)]:
            a = build_action(
                "ptz",
                {"direction": direction, "duration_ms": 200, "speed": 2, "lens": 0},
            )
            self.assertIn("command=" + str(command) + "&", a["path"])
            self.assertIn("command=" + str(command + 1) + "&", a["stop"])
            self.assertEqual(a["duration"], 0.2)
        for invalid in [True, 0, 3000, "100"]:
            with self.assertRaises(ControlError):
                build_action("ptz", {"direction": "left", "duration_ms": invalid})

    def test_console_cannot_override_account_or_address_another_host(self):
        for path in [
            "http://other/get_status.cgi?",
            "../get_status.cgi?",
            "get_status.cgi?userId=999",
            "get_status.cgi?pwd=secret",
            "get_status.cgi?x=%0Ainjected",
        ]:
            with self.assertRaises(ControlError):
                build_action("native", {"path": path})
        self.assertEqual(
            build_action("native", {"path": "get_status.cgi?"})["path"],
            "get_status.cgi?",
        )

    def test_variable_parser_handles_semicolons_without_eval(self):
        raw = b"""result=0;var model="multi; lens";var haveMotor=1;var list=[1,2,3];var evil=__import__('os');"""
        parsed = parse_variables(raw)
        self.assertEqual(parsed["model"], "multi; lens")
        self.assertEqual(parsed["haveMotor"], 1)
        self.assertEqual(parsed["list"], [1, 2, 3])
        self.assertIsInstance(parsed["evil"], str)

    def test_metadata_excludes_secrets_and_nested_secret_fields(self):
        data = {
            "sys_ver": "1.2",
            "wifi_key": "secret",
            "user1_pwd": "pw",
            "loginToken": "token",
            "arbitrary": "native-secret",
            "nested": {"password": "PRIVATE-VALUE", "width": 448},
        }
        safe = public_fields(data, secrets=("native-secret",))
        self.assertNotIn("secret", str(safe))
        self.assertNotIn("PRIVATE-VALUE", str(safe))
        self.assertEqual(safe["nested"], {"width": 448})

    def test_ptz_stop_attempted_when_move_transport_fails(self):
        sent = []

        class Session:
            def write(self, channel, request, timeout):
                sent.append(request)
                if len(sent) == 1:
                    raise OSError("failed")

        with self.assertRaises(OSError):
            execute_action(
                Session(),
                {"password": "native"},
                build_action("ptz", {"direction": "up", "duration_ms": 100}),
            )
        self.assertEqual(len(sent), 2)
        self.assertIn(b"command=1&", sent[1])

    def test_expired_job_does_not_execute_late(self):
        job = ControlJob(build_action("ptz", {"direction": "up"}), ttl=0.01)
        time.sleep(0.02)
        self.assertFalse(job.claim())
        self.assertTrue(job.done.is_set())

    def test_sd_index_arrays_are_parsed_as_data(self):
        parsed = parse_variables(
            b'var record_name0=new Array();record_name0[0]="20261031";record_name0[1]="20261030";var record_datenum=2;'
        )
        self.assertEqual(parsed["record_name0"], ["20261031", "20261030"])

    def test_partial_control_reply_is_retained_until_complete(self):
        from okam_bridge.controls import read_control

        payload = b"result=0;"
        packet = struct.pack("<HHHH", 0x0A01, 0x6003, len(payload), 0) + payload

        class Session:
            _channel_buffers = [bytearray(packet[:10])]

            def _pump(self):
                pass

        session = Session()
        self.assertIsNone(read_control(session, 0))
        self.assertEqual(bytes(session._channel_buffers[0]), packet[:10])
        session._channel_buffers[0].extend(packet[10:])
        self.assertEqual(read_control(session, 0), (0x6003, payload))
        self.assertEqual(session._channel_buffers[0], bytearray())

    def test_raw_json_and_embedded_json_responses_hide_secret_keys(self):
        from okam_bridge.controls import redact_response

        for raw in [
            '{"wifi_password":"private-network-password","token":"private-camera-token","width":448}',
            'var config={"wifi_password":"private-network-password","token":"private-camera-token"};',
        ]:
            text = redact_response(raw)
            self.assertNotIn("private-network-password", text)
            self.assertNotIn("private-camera-token", text)

    def test_sdk_volume_presets_and_firmware_step(self):
        self.assertIn(
            "param=24&value=31&",
            build_action("volume", {"channel": "microphone", "value": 31})["path"],
        )
        self.assertIn(
            "param=25&value=0&",
            build_action("volume", {"channel": "speaker", "value": 0})["path"],
        )
        for slot in range(1, 6):
            self.assertIn(
                "command=" + str(29 + 2 * slot) + "&",
                build_action("preset", {"slot": slot, "operation": "goto"})["path"],
            )
        self.assertEqual(
            build_action("ptz_step", {"direction": "right"})["path"],
            "decoder_control.cgi?command=6&onestep=1&",
        )
        with self.assertRaises(ControlError):
            build_action("volume", {"channel": "speaker", "value": 100})

    def test_night_followup_is_not_sent_after_disconnect(self):
        stop = threading.Event()
        calls = []

        def first(*args, **kwargs):
            calls.append(args[2]["path"])
            stop.set()
            return {"state": "confirmed", "result": 0, "transport_acknowledged": True}

        action = build_action("image", {"field": "night", "value": 1})
        with patch("okam_bridge.controls._execute_single", side_effect=first):
            result = execute_action(object(), {}, action, stop)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["state"], "interrupted")

    def test_interruption_during_followup_is_reported_as_interrupted(self):
        action = build_action("image", {"field": "night", "value": 2})
        with patch(
            "okam_bridge.controls._execute_single",
            side_effect=[{"state": "confirmed", "result": 0}, {"state": "interrupted"}],
        ):
            result = execute_action(object(), {}, action, threading.Event())
        self.assertEqual(result["state"], "interrupted")

    def test_native_json_responses_are_available_as_metadata(self):
        self.assertEqual(
            parse_variables(b'{"width":448,"modes":[1,2,4]}'),
            {"width": 448, "modes": [1, 2, 4]},
        )
        self.assertEqual(
            parse_variables(b'["20261031","20261030"]'),
            {"items": ["20261031", "20261030"]},
        )
