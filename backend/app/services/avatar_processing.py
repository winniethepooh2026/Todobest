from __future__ import annotations

import hashlib
import io
import secrets
import warnings
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

ALLOWED_AVATAR_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
ALLOWED_AVATAR_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
GOOGLE_AVATAR_HOST_SUFFIX = ".googleusercontent.com"
AVATAR_DOWNLOAD_CHUNK_BYTES = 64 * 1024
AVATAR_WEBP_QUALITIES = (78, 70, 62, 54)
METADATA_KEYS = frozenset({"exif", "icc_profile", "xmp", "comment", "description"})


class AvatarError(RuntimeError):
    pass


class InvalidAvatarError(AvatarError):
    pass


class AvatarSourceUnavailableError(AvatarError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessedAvatar:
    data: bytes
    content_hash: str
    width: int
    height: int
    size_bytes: int


def validate_google_picture_url(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise InvalidAvatarError("Google returned an invalid profile picture URL")
    if (
        value != value.strip()
        or not value.isprintable()
        or any(character.isspace() for character in value)
    ):
        raise InvalidAvatarError("Google returned an invalid profile picture URL")
    try:
        value.encode("ascii")
        parsed = urlsplit(value)
        port = parsed.port
    except (UnicodeEncodeError, ValueError) as exc:
        raise InvalidAvatarError("Google returned an invalid profile picture URL") from exc

    hostname = (parsed.hostname or "").rstrip(".").casefold()
    if (
        parsed.scheme != "https"
        or not hostname.endswith(GOOGLE_AVATAR_HOST_SUFFIX)
        or hostname == GOOGLE_AVATAR_HOST_SUFFIX.removeprefix(".")
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path.startswith("/")
        or parsed.fragment
    ):
        raise InvalidAvatarError("Google returned an invalid profile picture URL")
    return value


def avatar_source_hash(picture_url: str) -> str:
    return hashlib.sha256(picture_url.encode("ascii")).hexdigest()


async def download_google_avatar(picture_url: str) -> bytes:
    picture_url = validate_google_picture_url(picture_url) or ""
    timeout = httpx.Timeout(
        connect=min(5.0, settings.avatar_download_timeout_seconds),
        read=settings.avatar_download_timeout_seconds,
        write=min(5.0, settings.avatar_download_timeout_seconds),
        pool=min(5.0, settings.avatar_download_timeout_seconds),
    )
    limits = httpx.Limits(max_connections=2, max_keepalive_connections=1)

    try:
        async with (
            httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                follow_redirects=False,
                trust_env=False,
            ) as client,
            client.stream(
                "GET",
                picture_url,
                headers={"Accept": "image/webp,image/png,image/jpeg"},
            ) as response,
        ):
            if response.status_code == 429 or response.is_server_error:
                raise AvatarSourceUnavailableError(
                    "Google profile picture is temporarily unavailable"
                )
            if response.is_redirect or response.is_error:
                raise InvalidAvatarError("Google profile picture could not be downloaded")

            content_type = response.headers.get("Content-Type", "")
            content_type = content_type.partition(";")[0].strip().casefold()
            if content_type not in ALLOWED_AVATAR_CONTENT_TYPES:
                raise InvalidAvatarError("Google profile picture has an unsupported type")

            declared_length = response.headers.get("Content-Length")
            if declared_length:
                try:
                    size = int(declared_length)
                except ValueError as exc:
                    raise InvalidAvatarError("Google profile picture has an invalid size") from exc
                if size <= 0 or size > settings.avatar_source_max_bytes:
                    raise InvalidAvatarError("Google profile picture exceeds the size limit")

            raw = bytearray()
            async for chunk in response.aiter_bytes(AVATAR_DOWNLOAD_CHUNK_BYTES):
                if len(raw) + len(chunk) > settings.avatar_source_max_bytes:
                    raise InvalidAvatarError("Google profile picture exceeds the size limit")
                raw.extend(chunk)
    except (InvalidAvatarError, AvatarSourceUnavailableError):
        raise
    except httpx.HTTPError as exc:
        raise AvatarSourceUnavailableError(
            "Google profile picture is temporarily unavailable"
        ) from exc

    if not raw:
        raise InvalidAvatarError("Google profile picture is empty")
    return bytes(raw)


def _validate_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise InvalidAvatarError("Avatar dimensions are invalid")
    if (
        width > settings.avatar_source_max_dimension
        or height > settings.avatar_source_max_dimension
    ):
        raise InvalidAvatarError("Avatar dimensions exceed the configured limit")
    if width * height > settings.avatar_source_max_pixels:
        raise InvalidAvatarError("Avatar pixel count exceeds the configured limit")


def _decode_avatar(raw: bytes) -> Image.Image:
    if not raw or len(raw) > settings.avatar_source_max_bytes:
        raise InvalidAvatarError("Avatar source is outside the configured size limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                source_format = (probe.format or "").upper()
                if source_format not in ALLOWED_AVATAR_FORMATS:
                    raise InvalidAvatarError("Only static JPEG, PNG and WebP avatars are allowed")
                _validate_dimensions(*probe.size)
                if getattr(probe, "is_animated", False) or getattr(probe, "n_frames", 1) != 1:
                    raise InvalidAvatarError("Animated avatars are not allowed")
                probe.verify()

            with Image.open(io.BytesIO(raw)) as source:
                if (source.format or "").upper() != source_format:
                    raise InvalidAvatarError("Avatar format could not be verified")
                _validate_dimensions(*source.size)
                if getattr(source, "is_animated", False) or getattr(source, "n_frames", 1) != 1:
                    raise InvalidAvatarError("Animated avatars are not allowed")
                oriented = ImageOps.exif_transpose(source)
                _validate_dimensions(*oriented.size)
                oriented.load()
                return oriented.copy()
    except InvalidAvatarError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise InvalidAvatarError("Avatar is not a valid supported image") from exc


def _encode_clean_webp(image: Image.Image) -> bytes:
    size = settings.avatar_output_size
    fitted = ImageOps.fit(
        image.convert("RGBA"),
        (size, size),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    background = Image.new("RGBA", fitted.size, (245, 245, 244, 255))
    background.alpha_composite(fitted)
    rgb = background.convert("RGB")
    clean = Image.frombytes("RGB", rgb.size, rgb.tobytes())

    for quality in AVATAR_WEBP_QUALITIES:
        output = io.BytesIO()
        clean.save(
            output,
            format="WEBP",
            quality=quality,
            method=6,
            exif=b"",
            icc_profile=None,
            xmp=b"",
        )
        encoded = output.getvalue()
        if len(encoded) <= settings.avatar_output_max_bytes:
            return encoded
    raise InvalidAvatarError("Normalized avatar exceeds the storage size limit")


def validate_processed_avatar(avatar: ProcessedAvatar) -> None:
    if (
        avatar.size_bytes != len(avatar.data)
        or not avatar.data
        or avatar.size_bytes > settings.avatar_output_max_bytes
        or avatar.width != settings.avatar_output_size
        or avatar.height != settings.avatar_output_size
    ):
        raise InvalidAvatarError("Normalized avatar metadata is invalid")
    digest = hashlib.sha256(avatar.data).hexdigest()
    if not secrets.compare_digest(digest, avatar.content_hash):
        raise InvalidAvatarError("Normalized avatar checksum is invalid")

    try:
        with Image.open(io.BytesIO(avatar.data)) as probe:
            if (
                probe.format != "WEBP"
                or probe.size != (settings.avatar_output_size, settings.avatar_output_size)
                or getattr(probe, "is_animated", False)
                or getattr(probe, "n_frames", 1) != 1
                or any(probe.info.get(key) for key in METADATA_KEYS)
                or bool(probe.getexif())
            ):
                raise InvalidAvatarError("Normalized avatar failed verification")
            probe.verify()
    except InvalidAvatarError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidAvatarError("Normalized avatar failed verification") from exc


def process_avatar(raw: bytes) -> ProcessedAvatar:
    image = _decode_avatar(raw)
    try:
        encoded = _encode_clean_webp(image)
    finally:
        image.close()
    avatar = ProcessedAvatar(
        data=encoded,
        content_hash=hashlib.sha256(encoded).hexdigest(),
        width=settings.avatar_output_size,
        height=settings.avatar_output_size,
        size_bytes=len(encoded),
    )
    validate_processed_avatar(avatar)
    return avatar
