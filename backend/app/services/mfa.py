"""TOTP and one-use recovery codes. Secrets are encrypted with the data key."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from urllib.parse import quote

from app.core.encryption import EncryptedValue, encrypted_field_aad, get_data_cipher
from app.models import User


def create_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_uri(email: str, secret: str) -> str:
    return f"otpauth://totp/Noki:{quote(email)}?secret={secret}&issuer=Noki&algorithm=SHA1&digits=6&period=30"


def seal_secret(user: User, secret: str) -> str:
    sealed = get_data_cipher().encrypt(
        secret.encode("ascii"), aad=encrypted_field_aad("users", user.id, "totp")
    )
    return ".".join(
        base64.urlsafe_b64encode(part).decode("ascii").rstrip("=")
        for part in (sealed.nonce, sealed.ciphertext, sealed.tag)
    )


def open_secret(user: User, stored: str) -> str:
    parts = [base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)) for part in stored.split(".")]
    if len(parts) != 3:
        raise ValueError("Invalid stored TOTP secret")
    return (
        get_data_cipher()
        .decrypt(
            EncryptedValue(ciphertext=parts[1], nonce=parts[0], tag=parts[2]),
            aad=encrypted_field_aad("users", user.id, "totp"),
        )
        .decode("ascii")
    )


def _totp_at(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def check_totp(user: User, code: str, *, now: int | None = None) -> bool:
    if not user.totp_secret or len(code) != 6 or not code.isascii() or not code.isdigit():
        return False
    secret = open_secret(user, user.totp_secret)
    current = int((time.time() if now is None else now) // 30)
    for counter in (current - 1, current, current + 1):
        if counter > user.totp_last_counter and hmac.compare_digest(
            _totp_at(secret, counter), code
        ):
            user.totp_last_counter = counter
            return True
    return False


def create_recovery_codes() -> tuple[list[str], str]:
    codes = [secrets.token_urlsafe(12) for _ in range(8)]
    hashes = [hashlib.sha256(code.encode("ascii")).hexdigest() for code in codes]
    return codes, json.dumps(hashes)


def check_recovery_code(user: User, code: str) -> bool:
    if not user.totp_recovery_hashes or len(code) > 128:
        return False
    digest = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
    hashes: list[str] = json.loads(user.totp_recovery_hashes)
    for index, stored in enumerate(hashes):
        if hmac.compare_digest(digest, stored):
            hashes.pop(index)
            user.totp_recovery_hashes = json.dumps(hashes)
            return True
    return False


def verify_second_factor(user: User, code: str) -> bool:
    return check_totp(user, code) or check_recovery_code(user, code)
