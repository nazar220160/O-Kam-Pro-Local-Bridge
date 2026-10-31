import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock

from okam_bridge.onvif import NS

NS.setdefault("tptz", "http://www.onvif.org/ver20/ptz/wsdl")
from okam_bridge.onvif_ptz import handle_ptz


class PTZTests(unittest.TestCase):
    def setUp(self):
        self.item = {
            "export_id": "camera",
            "ptz": True,
            "profiles": [{"token": "lens2", "lens": 2}],
        }
        self.registry = Mock()
        self.registry.ptz.return_value = {}

    def call(self, action, content=""):
        request = ET.fromstring(
            f'<p:{action} xmlns:p="{NS["tptz"]}" xmlns:t="{NS["tt"]}">{content}</p:{action}>'
        )
        response = ET.Element("{" + NS["tptz"] + "}" + action + "Response")
        handle_ptz(response, action, self.item, request, self.registry)
        return response

    def profile(self):
        return "<p:ProfileToken>lens2</p:ProfileToken>"

    def test_continuous_move_uses_actual_profile_and_caps_timeout(self):
        self.call(
            "ContinuousMove",
            self.profile()
            + '<p:Velocity><t:PanTilt x=".25" y="-1"/></p:Velocity><p:Timeout>PT2M</p:Timeout>',
        )
        self.registry.ptz.assert_called_once_with(
            "camera", "lens2", "continuous_move", {"x": 0.25, "y": -1.0, "timeout": 5.0}
        )

    def test_stop_default_and_explicit_false(self):
        self.call("Stop", self.profile())
        self.registry.ptz.assert_called_once_with(
            "camera", "lens2", "stop", {"pan_tilt": True, "zoom": False}
        )
        self.registry.ptz.reset_mock()
        self.call(
            "Stop",
            self.profile() + "<p:PanTilt>false</p:PanTilt><p:Zoom>false</p:Zoom>",
        )
        self.registry.ptz.assert_called_once_with(
            "camera", "lens2", "stop", {"pan_tilt": False, "zoom": False}
        )

    def test_invalid_requests_never_reach_registry(self):
        invalid = [
            (
                "ContinuousMove",
                self.profile() + '<p:Velocity><t:PanTilt x="NaN" y="0"/></p:Velocity>',
            ),
            (
                "ContinuousMove",
                self.profile() + '<p:Velocity><t:PanTilt x="inf" y="0"/></p:Velocity>',
            ),
            (
                "ContinuousMove",
                self.profile() + '<p:Velocity><t:PanTilt x="1.01" y="0"/></p:Velocity>',
            ),
            (
                "ContinuousMove",
                self.profile()
                + '<p:Velocity><t:PanTilt x="0" y="0" space="wrong"/></p:Velocity>',
            ),
            (
                "ContinuousMove",
                self.profile()
                + '<p:Velocity><t:PanTilt x="0" y="0"/><t:Zoom x="0"/></p:Velocity>',
            ),
            (
                "ContinuousMove",
                self.profile()
                + '<p:Velocity><t:PanTilt x="0" y="0"/></p:Velocity><p:Timeout>PT0S</p:Timeout>',
            ),
            (
                "ContinuousMove",
                self.profile()
                + '<p:Velocity><t:PanTilt x="0" y="0"/></p:Velocity><p:Timeout>P1D</p:Timeout>',
            ),
            (
                "ContinuousMove",
                self.profile()
                + '<p:Velocity><t:PanTilt x="0" y="0"/></p:Velocity><p:Timeout/>',
            ),
            ("Stop", "<p:ProfileToken>lens0</p:ProfileToken>"),
            ("Stop", self.profile() + self.profile()),
            ("Stop", self.profile() + "<p:PanTilt>maybe</p:PanTilt>"),
            ("Stop", self.profile() + "<p:PanTilt/>"),
            ("Stop", self.profile() + "<p:Zoom>true</p:Zoom>"),
            ("GetStatus", ""),
            ("AbsoluteMove", self.profile()),
            ("RelativeMove", self.profile()),
            ("SetConfiguration", ""),
            ("GotoPreset", self.profile() + "<p:PresetToken>preset6</p:PresetToken>"),
            (
                "GotoPreset",
                self.profile() + "<p:PresetToken>preset1</p:PresetToken><p:Speed/>",
            ),
        ]
        for action, content in invalid:
            with self.subTest(action=action, content=content):
                with self.assertRaises(ValueError):
                    self.call(action, content)
                self.registry.ptz.assert_not_called()

    def test_readonly_schema_structure_no_absolute_or_zoom(self):
        nodes = self.call("GetNodes")
        ptz_node = nodes.find("tptz:PTZNode", NS)
        self.assertEqual(ptz_node.get("token"), "lens2")
        self.assertEqual(
            ptz_node.findtext("tt:MaximumNumberOfPresets", namespaces=NS), "5"
        )
        self.assertEqual(ptz_node.findtext("tt:HomeSupported", namespaces=NS), "false")
        spaces = ptz_node.find("tt:SupportedPTZSpaces", NS)
        self.assertEqual(
            [n.tag for n in spaces],
            ["{" + NS["tt"] + "}ContinuousPanTiltVelocitySpace"],
        )
        configs = self.call("GetConfigurations").find("tptz:PTZConfiguration", NS)
        self.assertEqual(
            [n.tag.split("}")[-1] for n in configs],
            [
                "Name",
                "UseCount",
                "NodeToken",
                "DefaultContinuousPanTiltVelocitySpace",
                "DefaultPTZTimeout",
            ],
        )
        options = self.call(
            "GetConfigurationOptions",
            "<p:ConfigurationToken>lens2</p:ConfigurationToken>",
        )
        self.assertEqual(
            options.findtext(
                "tptz:PTZConfigurationOptions/tt:PTZTimeout/tt:Min", namespaces=NS
            ),
            "PT0.08S",
        )
        self.assertEqual(
            options.findtext(
                "tptz:PTZConfigurationOptions/tt:PTZTimeout/tt:Max", namespaces=NS
            ),
            "PT5S",
        )
        self.registry.ptz.assert_not_called()

    def test_readonly_tokens_are_checked(self):
        for action, field in [
            ("GetNode", "NodeToken"),
            ("GetConfiguration", "PTZConfigurationToken"),
            ("GetConfigurationOptions", "ConfigurationToken"),
        ]:
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    self.call(action, f"<p:{field}>wrong</p:{field}>")
        self.registry.ptz.assert_not_called()

    def test_status_has_move_state_and_utc_without_invented_position(self):
        self.registry.ptz.return_value = {"moving": True}
        status = self.call("GetStatus", self.profile()).find("tptz:PTZStatus", NS)
        self.assertEqual(
            status.findtext("tt:MoveStatus/tt:PanTilt", namespaces=NS), "MOVING"
        )
        self.assertIsNone(status.find("tt:Position", NS))
        self.assertTrue(status.findtext("tt:UtcTime", namespaces=NS).endswith("Z"))

    def test_status_unknown_and_idle_are_distinct(self):
        for value, expected in [(False, "IDLE"), (None, "UNKNOWN")]:
            self.registry.ptz.return_value = {"moving": value}
            response = self.call("GetStatus", self.profile())
            self.assertEqual(
                response.findtext(
                    "tptz:PTZStatus/tt:MoveStatus/tt:PanTilt", namespaces=NS
                ),
                expected,
            )

    def test_capabilities_state_position_is_unavailable(self):
        capabilities = self.call("GetServiceCapabilities").find("tptz:Capabilities", NS)
        self.assertEqual(capabilities.get("MoveStatus"), "true")
        self.assertEqual(capabilities.get("StatusPosition"), "false")
        self.registry.ptz.assert_not_called()

    def test_timeout_accepts_fraction_and_rejects_less_than_native_minimum(self):
        move = self.profile() + '<p:Velocity><t:PanTilt x="0" y="1"/></p:Velocity>'
        self.call("ContinuousMove", move + "<p:Timeout>PT0.08S</p:Timeout>")
        self.assertEqual(self.registry.ptz.call_args.args[3]["timeout"], 0.08)
        self.registry.ptz.reset_mock()
        with self.assertRaises(ValueError):
            self.call("ContinuousMove", move + "<p:Timeout>PT0.079S</p:Timeout>")
        self.registry.ptz.assert_not_called()

    def test_presets_only_report_actual_native_slots_without_position(self):
        self.registry.ptz.return_value = {
            "presets": [{"slot": 2, "name": "Door & gate"}]
        }
        response = self.call("GetPresets", self.profile())
        presets = response.findall("tptz:Preset", NS)
        self.assertEqual([p.get("token") for p in presets], ["preset2"])
        self.assertEqual(presets[0].findtext("tt:Name", namespaces=NS), "Door & gate")
        self.assertIsNone(presets[0].find("tt:PTZPosition", NS))
        self.call(
            "GotoPreset", self.profile() + "<p:PresetToken>preset2</p:PresetToken>"
        )
        self.registry.ptz.assert_called_with(
            "camera", "lens2", "goto_preset", {"slot": 2}
        )
        self.call(
            "RemovePreset", self.profile() + "<p:PresetToken>preset2</p:PresetToken>"
        )
        self.registry.ptz.assert_called_with(
            "camera", "lens2", "remove_preset", {"slot": 2}
        )

    def test_set_preset_returns_confirmed_slot(self):
        self.registry.ptz.return_value = {"slot": 3}
        response = self.call(
            "SetPreset", self.profile() + "<p:PresetName>Gate</p:PresetName>"
        )
        self.registry.ptz.assert_called_with(
            "camera", "lens2", "set_preset", {"slot": None, "name": "Gate"}
        )
        self.assertEqual(
            response.findtext("tptz:PresetToken", namespaces=NS), "preset3"
        )

    def test_disabled_ptz_has_no_metadata_or_commands(self):
        self.item["ptz"] = False
        with self.assertRaises(ValueError):
            self.call("GetNodes")
        self.registry.ptz.assert_not_called()


if __name__ == "__main__":
    unittest.main()
