import unittest
from unittest.mock import patch
from okam_bridge.accounts import AccountWorkspace, LANBackend, Record
from okam_bridge.vendor.account import AccountDevice


class Decoder:
    def decode(self, security, check):
        return "account-native-secret"


class DualCredentialsTests(unittest.TestCase):
    def record(self):
        return Record(
            "camera",
            AccountDevice(
                uid="ABCD123456ABCDE",
                name="Example",
                device_password="external-plaintext",
                security="a" * 32,
            ),
            check_value="123",
            account_token="authorized-token",
        )

    def test_encrypted_native_credentials_take_precedence_over_plaintext_external_password(
        self,
    ):
        backend = LANBackend("ffmpeg")
        backend.decoder = Decoder()
        with patch(
            "okam_bridge.accounts.resolve_client_id", return_value="ABCD123456ABCDE"
        ), patch("okam_bridge.accounts.get_service_parameter", return_value="test"):
            config = backend.prepare(self.record(), "123", "192.168.20.10", 1)
        self.assertEqual(config["password"], "account-native-secret")
        self.assertEqual(config["account_token"], "authorized-token")

    def test_explicit_native_password_reveal_uses_same_credential_selection(self):
        record = self.record()

        class Client:
            user_id = "123"
            raw_items = []

        backend = LANBackend("ffmpeg")
        backend.decoder = Decoder()
        workspace = AccountWorkspace("example", Client(), [], backend)
        workspace.records = {"camera": record}
        self.assertEqual(
            workspace.reveal_credentials("camera")["password"], "account-native-secret"
        )
        workspace.close()

    def test_legacy_plaintext_camera_does_not_require_decoder(self):
        record = Record(
            "camera",
            AccountDevice(
                uid="ABCD123456ABCDE", name="Legacy", device_password="legacy-native"
            ),
        )
        backend = LANBackend("ffmpeg")
        with patch(
            "okam_bridge.accounts.resolve_client_id", return_value="ABCD123456ABCDE"
        ), patch("okam_bridge.accounts.get_service_parameter", return_value="test"):
            config = backend.prepare(record, "123", "192.168.20.10", 1)
        self.assertEqual(config["password"], "legacy-native")
        self.assertNotIn("account_token", config)
