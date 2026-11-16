from __future__ import annotations

import json
import unicodedata
from typing import Any, Protocol

from app.core.encryption import (
    DataDecryptionError,
    DataEncryptionError,
    EncryptedValue,
    encrypted_field_aad,
    get_data_cipher,
)
from app.models import Comment, Page, Task, Todo, Upload
from app.schemas.pages import validate_editor_document


class EncryptedRecord(Protocol):
    id: object
    encryption_key_version: int


def _encrypt_bytes(
    record: EncryptedRecord,
    *,
    table_name: str,
    field_name: str,
    value: bytes,
) -> None:
    record_id = record.id
    if record_id is None:
        raise DataEncryptionError(
            "Encrypted records must have a stable id before private content is assigned."
        )
    encrypted = get_data_cipher().encrypt(
        value,
        aad=encrypted_field_aad(table_name, record_id, field_name),
    )
    setattr(record, f"{field_name}_ciphertext", encrypted.ciphertext)
    setattr(record, f"{field_name}_nonce", encrypted.nonce)
    setattr(record, f"{field_name}_tag", encrypted.tag)
    record.encryption_key_version = encrypted.key_version


def _decrypt_bytes(
    record: EncryptedRecord,
    *,
    table_name: str,
    field_name: str,
) -> bytes:
    key_version = record.encryption_key_version
    encrypted = EncryptedValue(
        ciphertext=getattr(record, f"{field_name}_ciphertext"),
        nonce=getattr(record, f"{field_name}_nonce"),
        tag=getattr(record, f"{field_name}_tag"),
        key_version=key_version,
    )
    return get_data_cipher().decrypt(
        encrypted,
        aad=encrypted_field_aad(
            table_name,
            record.id,
            field_name,
            key_version,
        ),
    )


def _encrypt_text(
    record: EncryptedRecord,
    *,
    table_name: str,
    field_name: str,
    value: str,
) -> None:
    _encrypt_bytes(
        record,
        table_name=table_name,
        field_name=field_name,
        value=value.encode(),
    )


def _decrypt_text(
    record: EncryptedRecord,
    *,
    table_name: str,
    field_name: str,
) -> str:
    try:
        return _decrypt_bytes(
            record,
            table_name=table_name,
            field_name=field_name,
        ).decode()
    except UnicodeDecodeError as exc:
        raise DataDecryptionError("Decrypted text is not valid UTF-8.") from exc


def set_task_title(task: Task, title: str) -> None:
    task.title_blind_index = blind_title_index(title)
    _encrypt_text(task, table_name="tasks", field_name="title", value=title)


def set_task_description(task: Task, description: str) -> None:
    _encrypt_text(
        task,
        table_name="tasks",
        field_name="description",
        value=description,
    )


def get_task_title(task: Task) -> str:
    return _decrypt_text(task, table_name="tasks", field_name="title")


def get_task_description(task: Task) -> str:
    return _decrypt_text(task, table_name="tasks", field_name="description")


def set_comment_body(comment: Comment, body: str) -> None:
    _encrypt_text(comment, table_name="task_comments", field_name="body", value=body)


def get_comment_body(comment: Comment) -> str:
    return _decrypt_text(comment, table_name="task_comments", field_name="body")


def set_page_title(page: Page, title: str) -> None:
    page.title_blind_index = blind_title_index(title)
    _encrypt_text(page, table_name="pages", field_name="title", value=title)


def set_page_content(page: Page, content: dict[str, Any], markdown: str) -> None:
    validate_editor_document(content)
    serialized = json.dumps(
        content,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    _encrypt_bytes(
        page,
        table_name="pages",
        field_name="content",
        value=serialized,
    )
    _encrypt_text(
        page,
        table_name="pages",
        field_name="markdown",
        value=markdown,
    )


def get_page_title(page: Page) -> str:
    return _decrypt_text(page, table_name="pages", field_name="title")


def get_page_content(page: Page) -> dict[str, Any]:
    raw = _decrypt_bytes(page, table_name="pages", field_name="content")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataDecryptionError("Decrypted Page content is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise DataDecryptionError("Decrypted Page content has an invalid document root.")
    try:
        return validate_editor_document(value)
    except ValueError as exc:
        raise DataDecryptionError("Decrypted Page content has an invalid editor document.") from exc


def get_page_markdown(page: Page) -> str:
    return _decrypt_text(page, table_name="pages", field_name="markdown")


def set_upload_original_name(upload: Upload, original_name: str) -> None:
    _encrypt_text(
        upload,
        table_name="uploads",
        field_name="original_name",
        value=original_name,
    )


def get_upload_original_name(upload: Upload) -> str:
    return _decrypt_text(
        upload,
        table_name="uploads",
        field_name="original_name",
    )


def set_todo_title(todo: Todo, title: str) -> None:
    todo.title_blind_index = blind_title_index(title)
    _encrypt_text(todo, table_name="todos", field_name="title", value=title)


def normalize_search_title(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def blind_title_index(value: str) -> bytes:
    return get_data_cipher().blind_index(
        normalize_search_title(value).encode(),
        purpose=b"title:v1",
    )


def set_todo_description(todo: Todo, description: str) -> None:
    _encrypt_text(
        todo,
        table_name="todos",
        field_name="description",
        value=description,
    )


def get_todo_title(todo: Todo) -> str:
    return _decrypt_text(todo, table_name="todos", field_name="title")


def get_todo_description(todo: Todo) -> str:
    return _decrypt_text(todo, table_name="todos", field_name="description")
