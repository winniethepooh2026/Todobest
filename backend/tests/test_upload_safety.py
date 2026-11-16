from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import FormData

from app.api.routes import uploads
from app.core.config import settings
from app.services.images import ProcessedImage, process_and_store_image


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1, 1), "red").save(output, "PNG")
    return output.getvalue()


async def test_saturated_image_processor_fails_fast() -> None:
    acquired = 0
    try:
        for _ in range(uploads.IMAGE_PROCESSING_CONCURRENCY):
            await uploads.image_processing_slots.acquire()
            acquired += 1

        with pytest.raises(HTTPException) as exc_info:
            await uploads._acquire_image_processing_slot()

        assert exc_info.value.status_code == 503
        assert exc_info.value.headers == {"Retry-After": "2"}
    finally:
        for _ in range(acquired):
            uploads.image_processing_slots.release()


async def test_slow_uploads_use_a_separate_bounded_receive_pool() -> None:
    acquired = 0
    try:
        for _ in range(uploads.UPLOAD_RECEIVE_CONCURRENCY):
            await uploads.upload_receive_slots.acquire()
            acquired += 1

        with pytest.raises(HTTPException) as exc_info:
            await uploads._acquire_upload_receive_slot()

        assert exc_info.value.status_code == 503
        assert exc_info.value.headers == {"Retry-After": "2"}
        assert not uploads.image_processing_slots.locked()
    finally:
        for _ in range(acquired):
            uploads.upload_receive_slots.release()


async def test_private_image_response_is_no_store_and_streams_open_handle(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    monkeypatch.setattr(settings, "min_upload_free_bytes", 0)
    processed = process_and_store_image(png_bytes())
    user_id = uuid4()
    upload = SimpleNamespace(owner_id=user_id, page_id=None)

    class FakeDB:
        async def scalar(self, _statement):
            return upload

    response = await uploads.get_image(
        processed.filename,
        SimpleNamespace(id=user_id),
        FakeDB(),
    )

    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-length"] == str(processed.size_bytes)
    body = b"".join([chunk async for chunk in response.body_iterator])
    if response.background is not None:
        await response.background()
    assert body == processed.path.read_bytes()


async def test_upload_quota_is_checked_under_user_lock_and_rejected_file_is_removed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored_path = tmp_path / f"{'c' * 32}.webp"
    stored_path.write_bytes(b"processed")
    processed = ProcessedImage(
        filename=stored_path.name,
        path=stored_path,
        width=10,
        height=10,
        size_bytes=stored_path.stat().st_size,
    )

    async def fake_process(_file: UploadFile) -> ProcessedImage:
        return processed

    monkeypatch.setattr(uploads, "_process_uploaded_image", fake_process)
    monkeypatch.setattr(uploads, "set_upload_original_name", lambda *_args: None)
    monkeypatch.setattr(settings, "upload_max_files_per_user", 1)

    class QuotaResult:
        def one(self) -> tuple[int, int]:
            return (1, 0)

    class FakeDB:
        def __init__(self) -> None:
            self.statements = []
            self.rolled_back = False

        async def execute(self, statement):
            self.statements.append(statement)
            return None if len(self.statements) == 1 else QuotaResult()

        async def rollback(self) -> None:
            self.rolled_back = True

        async def commit(self) -> None:
            raise AssertionError("Quota rejection must not commit")

        def add(self, _record) -> None:
            raise AssertionError("Quota rejection must not add an upload")

    db = FakeDB()
    user_id = uuid4()
    with pytest.raises(HTTPException) as exc_info:
        await uploads._process_and_persist_upload(
            user_id,
            db,
            UploadFile(BytesIO(b"source"), filename="source.png"),
        )

    assert exc_info.value.status_code == 409
    assert "FOR UPDATE" in str(db.statements[0])
    assert db.rolled_back
    assert not stored_path.exists()


def test_upload_endpoint_has_no_eager_fastapi_body_parameter() -> None:
    route = next(
        route
        for route in uploads.router.routes
        if getattr(route, "endpoint", None) is uploads.upload_image
    )
    assert route.dependant.body_params == []


def test_upload_requires_exactly_one_named_file_part() -> None:
    file = UploadFile(BytesIO(b"image"), filename="image.png")
    assert uploads._single_image_file(FormData([("file", file)])) is file

    with pytest.raises(HTTPException) as exc_info:
        uploads._single_image_file(
            FormData(
                [
                    ("file", file),
                    ("unexpected", "value"),
                ]
            )
        )
    assert exc_info.value.status_code == 400
