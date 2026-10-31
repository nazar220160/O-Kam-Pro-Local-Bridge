import hashlib
import struct
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs
from okam_bridge.credentials import CredentialDecoder, CredentialError
from okam_bridge.transport import authorize_account


class CredentialsTests(unittest.TestCase):
    def encrypted(self, password, check, key):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        p = password.encode()
        padding = 16 - len(p) % 16
        p += bytes([padding]) * padding
        enc = Cipher(
            algorithms.AES(hashlib.md5((check + key).encode()).digest()), modes.ECB()
        ).encryptor()
        return (enc.update(p) + enc.finalize()).hex()

    def test_client_key_is_selected_locally_without_exposing_password(self):
        security = self.encrypted("camera-secret", "12345", "example-vendor-key")
        decoder = CredentialDecoder(
            client_bytes=b"\0unrelated-string\0example-vendor-key\0"
        )
        self.assertEqual(decoder.decode(security, "12345"), "camera-secret")
        self.assertNotIn("camera-secret", repr(decoder))

    def test_missing_client_is_actionable(self):
        with self.assertRaisesRegex(CredentialError, "password_decoder_required"):
            CredentialDecoder().decode("a" * 32, "123")

    def test_wrong_client_and_bad_inputs_fail_closed(self):
        decoder = CredentialDecoder(client_bytes=b"\0unrelated-string\0")
        for sec, check in [("a" * 32, "123"), ("invalid", "123"), ("a" * 32, "12&3")]:
            with self.assertRaises(CredentialError):
                decoder.decode(sec, check)

    def test_camera_sequence_uses_current_account_and_encodes_token(self):
        sent = []
        with patch(
            "okam_bridge.transport.write_command",
            side_effect=lambda s, r: sent.append(r),
        ):
            authorize_account(
                object(),
                {
                    "account_id": "123",
                    "account_token": "tok&en",
                    "password": "native",
                    "compatibility_password": "888888",
                },
            )
        paths = [r[8:].decode() for r in sent]
        self.assertTrue(paths[0].startswith("GET /eye4_authentication.cgi?"))
        q = parse_qs(paths[0].split("?", 1)[1])
        self.assertEqual(q["loginAccount"], ["123"])
        self.assertEqual(q["loginToken"], ["tok&en"])
        self.assertTrue(paths[1].startswith("GET /check_user.cgi?"))
