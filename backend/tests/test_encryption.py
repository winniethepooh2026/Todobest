import base64
import json
from dataclasses import replace
from uuid import uuid4

import pytest

from app.core.encryption import (
    DataCipher,
    DataDecryptionError,
    DataEncryptionConfigurationError,
    DataEncryptionError,
)
from app.models import Page, Task, Upload
from app.services import content_encryption

TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()


def test_aes_gcm_round_trip_uses_unique_nonces() -> None:
    cipher = DataCipher(TEST_KEY)
    aad = b"noki:1:pages:page-id:title"

    first = cipher.encrypt("Секретная страница".encode(), aad=aad)
    second = cipher.encrypt("Секретная страница".encode(), aad=aad)

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert cipher.decrypt(first, aad=aad).decode() == "Секретная страница"
    assert len(first.nonce) == 12
    assert len(first.tag) == 16


def test_missing_encryption_key_is_rejected() -> None:
    with pytest.raises(DataEncryptionConfigurationError, match="DATA_ENCRYPTION_KEY"):
        DataCipher("")


@pytest.mark.parametrize("part", ["ciphertext", "nonce", "tag"])
def test_tampering_is_rejected(part: str) -> None:
    cipher = DataCipher(TEST_KEY)
    aad = b"noki:1:tasks:task-id:title"
    encrypted = cipher.encrypt(b"private issue", aad=aad)
    original = getattr(encrypted, part)
    tampered_bytes = bytes([original[0] ^ 1]) + original[1:]
    tampered = replace(encrypted, **{part: tampered_bytes})

    with pytest.raises(DataDecryptionError):
        cipher.decrypt(tampered, aad=aad)


def test_ciphertext_cannot_be_moved_to_another_field() -> None:
    cipher = DataCipher(TEST_KEY)
    encrypted = cipher.encrypt(
        b"private issue",
        aad=b"noki:1:tasks:task-id:title",
    )

    with pytest.raises(DataDecryptionError):
        cipher.decrypt(
            encrypted,
            aad=b"noki:1:tasks:task-id:description",
        )


def test_wrong_key_is_rejected_without_plaintext_fallback() -> None:
    first_cipher = DataCipher(TEST_KEY)
    second_key = base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode()
    second_cipher = DataCipher(second_key)
    aad = b"noki:1:tasks:task-id:description"
    encrypted = first_cipher.encrypt(b"never return this as fallback", aad=aad)

    with pytest.raises(DataDecryptionError):
        second_cipher.decrypt(encrypted, aad=aad)


def test_sensitive_plaintext_columns_are_not_in_models() -> None:
    assert "title" not in Task.__table__.c
    assert "description" not in Task.__table__.c
    assert "title" not in Page.__table__.c
    assert "content" not in Page.__table__.c
    assert "markdown" not in Page.__table__.c
    assert "original_name" not in Upload.__table__.c


def test_content_encryption_requires_a_stable_record_id(monkeypatch) -> None:
    cipher = DataCipher(TEST_KEY)
    monkeypatch.setattr(content_encryption, "get_data_cipher", lambda: cipher)
    task = Task()

    with pytest.raises(DataEncryptionError, match="stable id"):
        content_encryption.set_task_title(task, "Private title")


def test_empty_encrypted_values_round_trip(monkeypatch) -> None:
    cipher = DataCipher(TEST_KEY)
    monkeypatch.setattr(content_encryption, "get_data_cipher", lambda: cipher)

    task = Task(id=uuid4())
    content_encryption.set_task_description(task, "")
    assert content_encryption.get_task_description(task) == ""
    assert task.description_ciphertext == b""

    page = Page(id=uuid4())
    empty_document = {"type": "doc", "content": [{"type": "paragraph"}]}
    content_encryption.set_page_content(page, empty_document, "")
    assert content_encryption.get_page_content(page) == empty_document
    assert content_encryption.get_page_markdown(page) == ""
    assert page.markdown_ciphertext == b""


def test_decryption_does_not_reencrypt_or_mutate_record(monkeypatch) -> None:
    cipher = DataCipher(TEST_KEY)
    monkeypatch.setattr(content_encryption, "get_data_cipher", lambda: cipher)
    task = Task(id=uuid4())
    content_encryption.set_task_title(task, "Private title")
    encrypted_before = (
        task.title_ciphertext,
        task.title_nonce,
        task.title_tag,
        task.encryption_key_version,
    )

    assert content_encryption.get_task_title(task) == "Private title"
    assert content_encryption.get_task_title(task) == "Private title"
    assert (
        task.title_ciphertext,
        task.title_nonce,
        task.title_tag,
        task.encryption_key_version,
    ) == encrypted_before


def test_task_and_page_content_helpers_round_trip(monkeypatch) -> None:
    cipher = DataCipher(TEST_KEY)
    monkeypatch.setattr(content_encryption, "get_data_cipher", lambda: cipher)

    task = Task(id=uuid4())
    content_encryption.set_task_title(task, "Private title")
    content_encryption.set_task_description(task, "Private description")
    assert content_encryption.get_task_title(task) == "Private title"
    assert content_encryption.get_task_description(task) == "Private description"
    assert task.title_ciphertext != b"Private title"

    page = Page(id=uuid4())
    document = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Secret"}]}],
    }
    content_encryption.set_page_title(page, "Private Page")
    content_encryption.set_page_content(page, document, "# Private Page")
    assert content_encryption.get_page_title(page) == "Private Page"
    assert content_encryption.get_page_content(page) == document
    assert content_encryption.get_page_markdown(page) == "# Private Page"


def test_stored_editor_document_is_revalidated_on_read(monkeypatch) -> None:
    cipher = DataCipher(TEST_KEY)
    monkeypatch.setattr(content_encryption, "get_data_cipher", lambda: cipher)

    page = Page(id=uuid4())
    unsafe_document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": {"textAlign": "left;position:fixed"},
            }
        ],
    }
    serialized = json.dumps(unsafe_document, separators=(",", ":")).encode()
    content_encryption._encrypt_bytes(
        page,
        table_name="pages",
        field_name="content",
        value=serialized,
    )

    with pytest.raises(DataDecryptionError, match="invalid editor document"):
        content_encryption.get_page_content(page)
