from __future__ import annotations

import os
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core.config import settings
from app.services.images import (
    MAX_OUTPUT_HEIGHT,
    MAX_SOURCE_HEIGHT,
    InsufficientImageStorageError,
    InvalidImageError,
    UnsupportedImageFormatError,
    finalize_staged_image,
    open_image_for_read,
    process_and_store_image,
    restore_staged_image,
    stage_image_deletion,
)


@pytest.fixture(autouse=True)
def allow_test_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "min_upload_free_bytes", 0)


def encoded_image(
    image_format: str,
    *,
    size: tuple[int, int] = (32, 24),
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "#171717").save(output, image_format)
    return output.getvalue()


def test_actual_unsupported_image_format_is_rejected(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)

    with pytest.raises(UnsupportedImageFormatError):
        process_and_store_image(encoded_image("TIFF"))

    assert list(tmp_path.iterdir()) == []


def test_excessive_source_height_is_rejected_before_decode(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    raw = encoded_image("PNG", size=(1, MAX_SOURCE_HEIGHT + 1))

    with pytest.raises(ValueError, match="height"):
        process_and_store_image(raw)

    assert list(tmp_path.iterdir()) == []


def test_output_height_is_bounded(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    monkeypatch.setattr(settings, "max_image_width", 1)
    raw = encoded_image("PNG", size=(2, MAX_OUTPUT_HEIGHT))

    result = process_and_store_image(raw)

    assert result.height <= MAX_OUTPUT_HEIGHT
    assert result.width <= settings.max_image_width


def test_low_disk_reserve_rejects_before_writing_image(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    monkeypatch.setattr(settings, "min_upload_free_bytes", 10)
    monkeypatch.setattr(
        "app.services.images.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=10),
    )

    with pytest.raises(InsufficientImageStorageError):
        process_and_store_image(encoded_image("PNG"))

    assert list(tmp_path.iterdir()) == []


def test_image_is_opened_as_the_same_regular_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    result = process_and_store_image(encoded_image("PNG"))

    opened = open_image_for_read(result.filename)
    try:
        assert opened.size_bytes == result.size_bytes
        assert opened.stream.read() == result.path.read_bytes()
    finally:
        opened.stream.close()


def test_image_symlink_is_never_followed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    target = tmp_path / "private.txt"
    target.write_text("private", encoding="utf-8")
    link = tmp_path / f"{'b' * 32}.webp"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("Symlinks are unavailable on this platform")

    with pytest.raises(InvalidImageError, match="path"):
        open_image_for_read(link.name)


def test_staged_image_deletion_can_be_restored_and_finalized(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    filename = f"{'a' * 32}.webp"
    original = tmp_path / filename
    original.write_bytes(b"image")

    staged = stage_image_deletion(filename)
    assert staged is not None
    assert not original.exists()
    assert staged.staged_path.exists()

    restore_staged_image(staged)
    assert original.read_bytes() == b"image"
    assert not staged.staged_path.exists()

    staged = stage_image_deletion(filename)
    assert staged is not None
    os.utime(staged.staged_path, (0, 0))
    finalize_staged_image(staged)
    assert not original.exists()
    assert not staged.staged_path.exists()
