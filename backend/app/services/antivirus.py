from __future__ import annotations

import logging
import socket
import struct
from collections.abc import Iterator

from app.core.config import settings

CLAMD_CHUNK_BYTES = 64 * 1024
CLAMD_MAX_RESPONSE_BYTES = 4096
logger = logging.getLogger(__name__)


class MalwareScanError(RuntimeError):
    """Base class for fail-closed malware scanning failures."""


class MalwareDetectedError(MalwareScanError):
    pass


class MalwareScannerUnavailableError(MalwareScanError):
    pass


def _chunks(payload: bytes) -> Iterator[memoryview]:
    view = memoryview(payload)
    for offset in range(0, len(view), CLAMD_CHUNK_BYTES):
        yield view[offset : offset + CLAMD_CHUNK_BYTES]


def _connect() -> socket.socket:
    if settings.clamav_unix_socket is not None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(settings.clamav_timeout_seconds)
            connection.connect(str(settings.clamav_unix_socket))
        except OSError:
            connection.close()
            raise
        return connection
    return socket.create_connection(
        (settings.clamav_host, settings.clamav_port),
        timeout=settings.clamav_timeout_seconds,
    )


def _read_response(connection: socket.socket) -> bytes:
    response = bytearray()
    while len(response) <= CLAMD_MAX_RESPONSE_BYTES:
        chunk = connection.recv(min(1024, CLAMD_MAX_RESPONSE_BYTES + 1 - len(response)))
        if not chunk:
            break
        response.extend(chunk)
        if b"\0" in chunk:
            break
    if not response or len(response) > CLAMD_MAX_RESPONSE_BYTES:
        raise MalwareScannerUnavailableError("Antivirus returned an invalid response")
    return bytes(response).split(b"\0", maxsplit=1)[0].rstrip(b"\r\n")


def scan_avatar_bytes(payload: bytes) -> None:
    """Scan bytes through clamd INSTREAM and accept only an explicit CLEAN result."""

    max_bytes = max(settings.avatar_source_max_bytes, settings.avatar_output_max_bytes)
    if not payload or len(payload) > max_bytes:
        raise MalwareScannerUnavailableError("Antivirus input is outside the configured limit")
    if settings.avatar_malware_scan_mode == "disabled-for-testing":
        logger.warning(
            "SECURITY WARNING: avatar malware scan skipped by "
            "AVATAR_MALWARE_SCAN_MODE=disabled-for-testing"
        )
        return

    try:
        with _connect() as connection:
            connection.sendall(b"zINSTREAM\0")
            for chunk in _chunks(payload):
                connection.sendall(struct.pack("!I", len(chunk)))
                connection.sendall(chunk)
            connection.sendall(struct.pack("!I", 0))
            response = _read_response(connection)
    except MalwareScanError:
        raise
    except (OSError, TimeoutError) as exc:
        raise MalwareScannerUnavailableError("Antivirus is unavailable") from exc

    if response == b"stream: OK":
        return
    if response.startswith(b"stream: ") and response.endswith(b" FOUND"):
        raise MalwareDetectedError("Avatar failed the malware scan")
    raise MalwareScannerUnavailableError("Antivirus could not confirm a clean result")
