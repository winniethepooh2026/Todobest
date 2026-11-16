from __future__ import annotations

import base64
import hashlib
import io
import logging
import re
import threading
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.services.avatar_processing import ProcessedAvatar, validate_processed_avatar

AVATAR_OBJECT_KEY_PATTERN = re.compile(
    r"^avatars/(?P<user_id>[0-9a-f]{32})/(?P<content_hash>[0-9a-f]{64})\.webp$"
)
AVATAR_CACHE_CONTROL = "private, max-age=31536000, immutable"
S3_LIST_PAGE_SIZE = 1_000
MAX_AVATAR_LIST_PAGES = 100
AVATAR_MEMORY_CACHE_MAX_BYTES = 32 * 1024 * 1024
AVATAR_READ_CHUNK_BYTES = 64 * 1024

logger = logging.getLogger(__name__)

_avatar_memory_cache: OrderedDict[str, bytes] = OrderedDict()
_avatar_memory_cache_size = 0
_avatar_memory_cache_lock = threading.Lock()


class AvatarStorageError(RuntimeError):
    pass


class AvatarObjectNotFoundError(AvatarStorageError):
    pass


@dataclass(slots=True)
class OpenedAvatarObject:
    body: Any
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ListedAvatarObject:
    key: str
    last_modified: datetime


def avatar_object_key(user_id: UUID, content_hash: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
        raise AvatarStorageError("Avatar checksum is invalid")
    return f"avatars/{user_id.hex}/{content_hash}.webp"


def validate_avatar_object_key(key: str) -> re.Match[str]:
    match = AVATAR_OBJECT_KEY_PATTERN.fullmatch(key)
    if match is None:
        raise AvatarStorageError("Avatar object key is invalid")
    return match


def avatar_media_url(
    user_id: UUID,
    object_key: str | None,
    content_hash: str | None,
) -> str | None:
    if object_key is None or content_hash is None or not settings.avatar_storage_enabled:
        return None
    if object_key != avatar_object_key(user_id, content_hash):
        return None
    return f"/media/avatars/{user_id}/{content_hash}.webp"


def clear_avatar_memory_cache() -> None:
    """Clear the process-local immutable avatar cache (primarily for tests)."""

    global _avatar_memory_cache_size
    with _avatar_memory_cache_lock:
        _avatar_memory_cache.clear()
        _avatar_memory_cache_size = 0


def _cached_avatar(content_hash: str) -> bytes | None:
    with _avatar_memory_cache_lock:
        data = _avatar_memory_cache.get(content_hash)
        if data is not None:
            _avatar_memory_cache.move_to_end(content_hash)
        return data


def _cache_avatar(content_hash: str, data: bytes) -> None:
    global _avatar_memory_cache_size
    if len(data) > AVATAR_MEMORY_CACHE_MAX_BYTES:
        return
    with _avatar_memory_cache_lock:
        previous = _avatar_memory_cache.pop(content_hash, None)
        if previous is not None:
            _avatar_memory_cache_size -= len(previous)
        _avatar_memory_cache[content_hash] = data
        _avatar_memory_cache_size += len(data)
        while _avatar_memory_cache_size > AVATAR_MEMORY_CACHE_MAX_BYTES:
            _, evicted = _avatar_memory_cache.popitem(last=False)
            _avatar_memory_cache_size -= len(evicted)


def _close_avatar_body(body: Any) -> None:
    close = getattr(body, "close", None)
    if callable(close):
        with suppress(BotoCoreError, OSError):
            close()


def _read_verified_avatar_body(
    body: Any,
    *,
    expected_size: int,
    expected_content_hash: str,
) -> bytes:
    read = getattr(body, "read", None)
    if not callable(read):
        _close_avatar_body(body)
        raise AvatarStorageError("Avatar object metadata failed verification")

    chunks: list[bytes] = []
    total_size = 0
    try:
        while chunk := read(AVATAR_READ_CHUNK_BYTES):
            if not isinstance(chunk, bytes):
                raise AvatarStorageError("Avatar object content failed verification")
            total_size += len(chunk)
            if total_size > expected_size or total_size > settings.avatar_output_max_bytes:
                raise AvatarStorageError("Avatar object content failed verification")
            chunks.append(chunk)
    except AvatarStorageError:
        raise
    except (BotoCoreError, OSError) as exc:
        raise AvatarStorageError("Avatar object could not be read") from exc
    finally:
        _close_avatar_body(body)

    data = b"".join(chunks)
    if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_content_hash:
        raise AvatarStorageError("Avatar object content failed verification")
    return data


@lru_cache(maxsize=1)
def get_s3_client() -> Any:
    if not settings.avatar_storage_enabled:
        raise AvatarStorageError("Avatar object storage is not configured")
    return boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key.get_secret_value(),
        region_name=settings.aws_s3_region_name,
        endpoint_url=settings.aws_s3_endpoint_url,
        config=Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=10,
            max_pool_connections=10,
            retries={"mode": "standard", "total_max_attempts": 3},
            s3={"addressing_style": "auto"},
        ),
    )


def store_avatar(user_id: UUID, avatar: ProcessedAvatar) -> str:
    """The only S3 PUT path: revalidate the normalized avatar immediately before upload."""

    validate_processed_avatar(avatar)
    key = avatar_object_key(user_id, avatar.content_hash)
    content_md5 = base64.b64encode(hashlib.md5(avatar.data, usedforsecurity=False).digest()).decode(
        "ascii"
    )
    try:
        get_s3_client().put_object(
            Bucket=settings.aws_storage_bucket_name,
            Key=key,
            Body=avatar.data,
            ContentType="image/webp",
            ContentLength=avatar.size_bytes,
            ContentMD5=content_md5,
            CacheControl=AVATAR_CACHE_CONTROL,
            Metadata={"sha256": avatar.content_hash},
            ServerSideEncryption="AES256",
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise AvatarStorageError("Avatar could not be stored") from exc
    return key


def open_avatar(key: str, expected_content_hash: str) -> OpenedAvatarObject:
    match = validate_avatar_object_key(key)
    if match.group("content_hash") != expected_content_hash:
        raise AvatarStorageError("Avatar object checksum does not match its key")

    cached = _cached_avatar(expected_content_hash)
    if cached is not None:
        return OpenedAvatarObject(body=io.BytesIO(cached), size_bytes=len(cached))

    try:
        response = get_s3_client().get_object(
            Bucket=settings.aws_storage_bucket_name,
            Key=key,
        )
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            raise AvatarObjectNotFoundError("Avatar object was not found") from exc
        raise AvatarStorageError("Avatar object could not be read") from exc
    except (BotoCoreError, OSError) as exc:
        raise AvatarStorageError("Avatar object could not be read") from exc

    body = response.get("Body")
    size_bytes = response.get("ContentLength")
    content_type = str(response.get("ContentType", "")).casefold()
    metadata = response.get("Metadata")
    stored_hash = metadata.get("sha256") if isinstance(metadata, dict) else None
    if (
        body is None
        or not isinstance(size_bytes, int)
        or size_bytes <= 0
        or size_bytes > settings.avatar_output_max_bytes
        or content_type != "image/webp"
        or stored_hash != expected_content_hash
    ):
        _close_avatar_body(body)
        raise AvatarStorageError("Avatar object metadata failed verification")

    data = _read_verified_avatar_body(
        body,
        expected_size=size_bytes,
        expected_content_hash=expected_content_hash,
    )
    _cache_avatar(expected_content_hash, data)
    return OpenedAvatarObject(body=io.BytesIO(data), size_bytes=size_bytes)


def delete_avatar(key: str) -> None:
    validate_avatar_object_key(key)
    try:
        get_s3_client().delete_object(
            Bucket=settings.aws_storage_bucket_name,
            Key=key,
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise AvatarStorageError("Avatar object could not be deleted") from exc


def list_avatar_objects() -> list[ListedAvatarObject]:
    client = get_s3_client()
    objects: list[ListedAvatarObject] = []
    continuation_token: str | None = None
    seen_continuation_tokens: set[str] = set()
    page_count = 0
    try:
        while True:
            if page_count >= MAX_AVATAR_LIST_PAGES:
                logger.error(
                    "Avatar object listing exceeded its safety limit of %d S3 pages",
                    MAX_AVATAR_LIST_PAGES,
                )
                raise AvatarStorageError("Avatar object listing exceeded its safety page limit")
            request: dict[str, object] = {
                "Bucket": settings.aws_storage_bucket_name,
                "Prefix": "avatars/",
                "MaxKeys": S3_LIST_PAGE_SIZE,
            }
            if continuation_token is not None:
                request["ContinuationToken"] = continuation_token
            response = client.list_objects_v2(**request)
            page_count += 1
            if not isinstance(response, dict):
                raise AvatarStorageError("Avatar object listing returned an invalid page")
            contents = response.get("Contents", [])
            is_truncated = response.get("IsTruncated", False)
            if (
                not isinstance(contents, list)
                or len(contents) > S3_LIST_PAGE_SIZE
                or not isinstance(is_truncated, bool)
            ):
                raise AvatarStorageError("Avatar object listing returned an invalid page")
            for item in contents:
                if not isinstance(item, dict):
                    continue
                key = item.get("Key")
                last_modified = item.get("LastModified")
                if (
                    isinstance(key, str)
                    and isinstance(last_modified, datetime)
                    and AVATAR_OBJECT_KEY_PATTERN.fullmatch(key)
                ):
                    objects.append(ListedAvatarObject(key=key, last_modified=last_modified))
            if not is_truncated:
                break
            token = response.get("NextContinuationToken")
            if not isinstance(token, str) or not token or token in seen_continuation_tokens:
                raise AvatarStorageError("Avatar object listing could not continue safely")
            seen_continuation_tokens.add(token)
            continuation_token = token
    except AvatarStorageError:
        raise
    except (BotoCoreError, ClientError, OSError) as exc:
        raise AvatarStorageError("Avatar objects could not be listed") from exc
    return objects


def delete_avatar_objects(keys: list[str]) -> int:
    unique_keys = list(dict.fromkeys(keys))
    if not unique_keys:
        return 0
    if len(unique_keys) > 1000:
        raise AvatarStorageError("Too many avatar objects were selected for one delete request")
    for key in unique_keys:
        validate_avatar_object_key(key)
    try:
        response = get_s3_client().delete_objects(
            Bucket=settings.aws_storage_bucket_name,
            Delete={"Objects": [{"Key": key} for key in unique_keys], "Quiet": True},
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise AvatarStorageError("Avatar objects could not be deleted") from exc
    errors = response.get("Errors")
    if errors:
        raise AvatarStorageError("Some avatar objects could not be deleted")
    return len(unique_keys)
