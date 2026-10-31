"""Decode authorized account-issued camera secrets without external files.

The supported protocol uses a fixed vendor salt plus the account check value.
This interoperability constant is not an account or camera credential. Actual
passwords are decoded only from records returned by the authenticated account.
An optional client-file override supports alternate vendor salts; never executed.
Algorithm reference: okam-ha-native vp_credentials.py, MIT.
"""

import hashlib
from pathlib import Path
import re
import threading


# Fixed securityPwd protocol salt, verified against authorized account records.
_CAMERA_PASSWORD_SALT = "_+Vstarcam++20200715"


class CredentialError(ValueError):
    pass


class CredentialDecoder:
    def __init__(self, path=None, *, client_bytes=None):
        self.path = path
        self._data = client_bytes
        self._key = None
        self._lock = threading.Lock()

    @staticmethod
    def _decode(security, check, key):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        cipher = Cipher(
            algorithms.AES(
                hashlib.md5(
                    (check + key).encode("ascii"), usedforsecurity=False
                ).digest()
            ),
            modes.ECB(),
        )
        dec = cipher.decryptor()
        plain = dec.update(bytes.fromhex(security)) + dec.finalize()
        n = plain[-1]
        if not 1 <= n <= 15 or plain[-n:] != bytes([n]) * n:
            raise ValueError
        p = plain[:-n]
        if not p or any(c < 33 or c > 126 for c in p) or b"&" in p:
            raise ValueError
        return p.decode("ascii")

    def decode(self, security, check):
        if (
            not isinstance(security, str)
            or not re.fullmatch("[0-9A-Fa-f]{32}", security)
            or not isinstance(check, str)
            or not re.fullmatch("[0-9]{1,63}", check)
        ):
            raise CredentialError("encrypted_credentials_invalid")
        try:
            with self._lock:
                for key in dict.fromkeys((self._key, _CAMERA_PASSWORD_SALT)):
                    if not key:
                        continue
                    try:
                        password = self._decode(security, check, key)
                    except ValueError:
                        continue
                    self._key = key
                    return password
                if self._data is None:
                    if not self.path:
                        raise CredentialError("encrypted_credentials_invalid")
                    p = Path(self.path)
                    if (
                        not p.is_file()
                        or not 1024 <= p.stat().st_size <= 128 * 1024 * 1024
                    ):
                        raise CredentialError("credential_client_invalid")
                    self._data = p.read_bytes()
                matches = {}
                # Official SuperIPCam stores the password-key salt as an ASCII literal.
                candidates = set(
                    m.group().decode("ascii")
                    for m in re.finditer(
                        rb"(?<![!-~])[!-~]{8,128}(?![!-~])", self._data
                    )
                )
                for key in candidates:
                    try:
                        password = self._decode(security, check, key)
                    except ValueError:
                        continue
                    matches.setdefault(password, key)
                    if len(matches) > 1:
                        raise CredentialError("credential_key_ambiguous")
                if not matches:
                    raise CredentialError("credential_key_not_found")
                password, self._key = next(iter(matches.items()))
                self._data = None
                return password
        except ImportError:
            raise CredentialError("crypto_dependency_required") from None
        except OSError:
            raise CredentialError("credential_client_invalid") from None
