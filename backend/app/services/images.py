from __future__ import annotations

import io
import os
import re
import shutil
import stat
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

MAX_SOURCE_PIXELS = settings.upload_max_pixels
MAX_SOURCE_DIMENSION = 20_000
MAX_SOURCE_HEIGHT = settings.upload_max_height
MAX_OUTPUT_HEIGHT = settings.upload_max_height
ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF"})

Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
IMAGE_FILENAME_PATTERN = re.compile(r"^[0-9a-f]{32}\.webp$")
STAGED_IMAGE_PATTERN = re.compile(r"^\.(?P<filename>[0-9a-f]{32}\.webp)\.[0-9a-f]{32}\.deleting$")


class InvalidImageError(ValueError):
    pass


class UnsupportedImageFormatError(InvalidImageError):
    pass


class InsufficientImageStorageError(InvalidImageError):
    pass


@dataclass(slots=True)
class ProcessedImage:
    filename: str
    path: Path
    width: int
    height: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class StagedImageDeletion:
    original_path: Path
    staged_path: Path


@dataclass(slots=True)
class OpenedImage:
    stream: BinaryIO
    size_bytes: int


def _validate_source_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise InvalidImageError("Image dimensions are invalid")
    if width > MAX_SOURCE_DIMENSION:
        raise InvalidImageError(f"Image width exceeds the {MAX_SOURCE_DIMENSION}px limit")
    if height > MAX_SOURCE_HEIGHT:
        raise InvalidImageError(f"Image height exceeds the {MAX_SOURCE_HEIGHT}px limit")
    if width * height > MAX_SOURCE_PIXELS:
        raise InvalidImageError(f"Image exceeds the {MAX_SOURCE_PIXELS:,}-pixel limit")


def process_and_store_image(raw: bytes) -> ProcessedImage:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                source_format = (probe.format or "").upper()
                if source_format not in ALLOWED_IMAGE_FORMATS:
                    raise UnsupportedImageFormatError(
                        "Only JPEG, PNG, WebP and GIF images are supported"
                    )
                _validate_source_dimensions(*probe.size)
                probe.verify()
            with Image.open(io.BytesIO(raw)) as source:
                if (source.format or "").upper() != source_format:
                    raise InvalidImageError("Image format could not be verified")
                _validate_source_dimensions(*source.size)
                source.seek(0)
                image = ImageOps.exif_transpose(source)
                _validate_source_dimensions(*image.size)
                image.load()
    except UnsupportedImageFormatError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
    ) as exc:
        raise InvalidImageError("File is not a valid supported image") from exc

    if image.width > settings.max_image_width or image.height > MAX_OUTPUT_HEIGHT:
        image.thumbnail(
            (settings.max_image_width, MAX_OUTPUT_HEIGHT),
            Image.Resampling.LANCZOS,
        )

    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")

    output = io.BytesIO()
    image.save(output, format="WEBP", quality=86, method=6)
    processed = output.getvalue()

    filename = f"{uuid4().hex}.webp"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(settings.upload_dir).free
    if free_bytes - len(processed) < settings.min_upload_free_bytes:
        raise InsufficientImageStorageError("Image storage is temporarily full")
    destination = safe_image_path(filename)
    descriptor: int | None = None
    created = False
    try:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(destination, flags, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as output_file:
            descriptor = None
            output_file.write(processed)
            output_file.flush()
            os.fsync(output_file.fileno())
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            destination.unlink(missing_ok=True)
        raise

    return ProcessedImage(
        filename=filename,
        path=destination,
        width=image.width,
        height=image.height,
        size_bytes=len(processed),
    )


def safe_image_path(filename: str) -> Path:
    if not IMAGE_FILENAME_PATTERN.fullmatch(filename):
        raise InvalidImageError("Invalid image filename")
    upload_root = settings.upload_dir.resolve()
    candidate = settings.upload_dir / filename
    try:
        if candidate.is_symlink() or candidate.resolve(strict=False).parent != upload_root:
            raise InvalidImageError("Invalid image path")
    except OSError as exc:
        raise InvalidImageError("Invalid image path") from exc
    return candidate


def open_image_for_read(filename: str) -> OpenedImage:
    path = safe_image_path(filename)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise InvalidImageError("Image not found") from exc

    try:
        opened_stat = os.fstat(descriptor)
        path_stat = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or (opened_stat.st_dev, opened_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise InvalidImageError("Invalid image path")
        return OpenedImage(
            stream=os.fdopen(descriptor, "rb"),
            size_bytes=opened_stat.st_size,
        )
    except Exception:
        os.close(descriptor)
        raise


def stage_image_deletion(
    filename: str,
    *,
    recover_existing: bool = True,
) -> StagedImageDeletion | None:
    original_path = safe_image_path(filename)
    staged_path = settings.upload_dir / f".{filename}.{uuid4().hex}.deleting"
    try:
        os.replace(original_path, staged_path)
    except FileNotFoundError:
        if not recover_existing:
            return None
        existing = next(
            (
                deletion
                for deletion in list_staged_image_deletions()
                if deletion.original_path == original_path
            ),
            None,
        )
        return existing
    return StagedImageDeletion(
        original_path=original_path,
        staged_path=staged_path,
    )


def restore_staged_image(deletion: StagedImageDeletion | None) -> None:
    if deletion is None or not deletion.staged_path.exists():
        return
    if deletion.original_path.exists():
        deletion.staged_path.unlink(missing_ok=True)
        return
    os.replace(deletion.staged_path, deletion.original_path)


def finalize_staged_image(deletion: StagedImageDeletion | None) -> None:
    if deletion is not None:
        deletion.staged_path.unlink(missing_ok=True)


def list_staged_image_deletions() -> list[StagedImageDeletion]:
    deletions: list[StagedImageDeletion] = []
    if not settings.upload_dir.is_dir():
        return deletions
    for path in settings.upload_dir.iterdir():
        match = STAGED_IMAGE_PATTERN.fullmatch(path.name)
        if match and path.is_file():
            deletions.append(
                StagedImageDeletion(
                    original_path=safe_image_path(match.group("filename")),
                    staged_path=path,
                )
            )
    return deletions


def list_stored_image_paths() -> list[Path]:
    if not settings.upload_dir.is_dir():
        return []
    return [
        path
        for path in settings.upload_dir.iterdir()
        if IMAGE_FILENAME_PATTERN.fullmatch(path.name) and (path.is_symlink() or path.is_file())
    ]


def extract_image_filenames(document: dict[str, object]) -> set[str]:
    filenames: set[str] = set()

    def walk(node: object) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "image":
            attrs = node.get("attrs")
            src = attrs.get("src") if isinstance(attrs, dict) else None
            if isinstance(src, str) and src.startswith("/media/images/"):
                filename = src.removeprefix("/media/images/")
                if IMAGE_FILENAME_PATTERN.fullmatch(filename):
                    filenames.add(filename)
        children = node.get("content")
        if isinstance(children, list):
            for child in children:
                walk(child)

    walk(document)
    return filenames
