from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from dataclasses import dataclass
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

AES_256_KEY_BYTES = 32
GCM_NONCE_BYTES = 12
GCM_TAG_BYTES = 16
CURRENT_DATA_KEY_VERSION = 1


class DataEncryptionError(RuntimeError):
    """Base error for encrypted application data."""


class DataEncryptionConfigurationError(DataEncryptionError):
    """Raised when the backend data-encryption key is missing or invalid."""


class DataDecryptionError(DataEncryptionError):
    """Raised when encrypted data cannot be authenticated and decrypted."""


@dataclass(frozen=True, slots=True)
class EncryptedValue:
    ciphertext: bytes
    nonce: bytes
    tag: bytes
    key_version: int = CURRENT_DATA_KEY_VERSION


def decode_data_encryption_key(encoded_key: str) -> bytes:
    value = encoded_key.strip()
    if not value:
        raise DataEncryptionConfigurationError(
            "DATA_ENCRYPTION_KEY is required. Configure a base64-encoded 32-byte key."
        )

    padded = value + ("=" * (-len(value) % 4))
    try:
        key = base64.b64decode(
            padded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise DataEncryptionConfigurationError(
            "DATA_ENCRYPTION_KEY must be valid base64 for exactly 32 random bytes."
        ) from exc

    if len(key) != AES_256_KEY_BYTES:
        raise DataEncryptionConfigurationError(
            "DATA_ENCRYPTION_KEY must decode to exactly 32 bytes for AES-256-GCM."
        )
    return key


def encrypted_field_aad(
    table_name: str,
    record_id: object,
    field_name: str,
    key_version: int = CURRENT_DATA_KEY_VERSION,
) -> bytes:
    return f"noki:{key_version}:{table_name}:{record_id}:{field_name}".encode()


class DataCipher:
    def __init__(self, encoded_key: str) -> None:
        key = decode_data_encryption_key(encoded_key)
        self._aesgcm = AESGCM(key)
        self._blind_index_key = hmac.new(
            key,
            b"noki:blind-index:key:v1",
            hashlib.sha256,
        ).digest()

    def blind_index(self, value: bytes, *, purpose: bytes) -> bytes:
        return hmac.new(
            self._blind_index_key,
            purpose + b":" + value,
            hashlib.sha256,
        ).digest()

    def encrypt(
        self,
        plaintext: bytes,
        *,
        aad: bytes,
        key_version: int = CURRENT_DATA_KEY_VERSION,
    ) -> EncryptedValue:
        if key_version != CURRENT_DATA_KEY_VERSION:
            raise DataEncryptionConfigurationError(
                f"Unsupported DATA_ENCRYPTION_KEY version: {key_version}"
            )
        nonce = os.urandom(GCM_NONCE_BYTES)
        sealed = self._aesgcm.encrypt(nonce, plaintext, aad)
        return EncryptedValue(
            ciphertext=sealed[:-GCM_TAG_BYTES],
            nonce=nonce,
            tag=sealed[-GCM_TAG_BYTES:],
            key_version=key_version,
        )

    def decrypt(
        self,
        encrypted: EncryptedValue,
        *,
        aad: bytes,
    ) -> bytes:
        if encrypted.key_version != CURRENT_DATA_KEY_VERSION:
            raise DataDecryptionError(
                f"Encrypted data uses unsupported key version {encrypted.key_version}."
            )
        try:
            nonce = bytes(encrypted.nonce)
            ciphertext = bytes(encrypted.ciphertext)
            tag = bytes(encrypted.tag)
        except (TypeError, ValueError) as exc:
            raise DataDecryptionError("Encrypted data has invalid AES-GCM values.") from exc

        if len(nonce) != GCM_NONCE_BYTES or len(tag) != GCM_TAG_BYTES:
            raise DataDecryptionError("Encrypted data has invalid AES-GCM metadata.")

        try:
            return self._aesgcm.decrypt(
                nonce,
                ciphertext + tag,
                aad,
            )
        except (InvalidTag, ValueError) as exc:
            raise DataDecryptionError(
                "Encrypted data failed authentication and could not be decrypted."
            ) from exc


@lru_cache
def get_data_cipher() -> DataCipher:
    return DataCipher(settings.data_encryption_key)
