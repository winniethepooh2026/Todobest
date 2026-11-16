"""Encrypt private content and complete Space memberships.

Revision ID: 0002_secure_content
Revises: 0001_initial
Create Date: 2026-07-27
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config import settings
from app.core.encryption import (
    CURRENT_DATA_KEY_VERSION,
    DataCipher,
    EncryptedValue,
    encrypted_field_aad,
)

revision: str = "0002_secure_content"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cipher() -> DataCipher:
    # Deliberately required even for an empty database so a deployment cannot
    # start with an encryption-ready schema but no usable encryption key.
    return DataCipher(settings.data_encryption_key)


def _encrypt(
    cipher: DataCipher,
    *,
    table_name: str,
    record_id: object,
    field_name: str,
    plaintext: bytes,
) -> dict[str, Any]:
    value = cipher.encrypt(
        plaintext,
        aad=encrypted_field_aad(table_name, record_id, field_name),
    )
    return {
        f"{field_name}_ciphertext": value.ciphertext,
        f"{field_name}_nonce": value.nonce,
        f"{field_name}_tag": value.tag,
    }


def _decrypt(
    cipher: DataCipher,
    *,
    table_name: str,
    record_id: object,
    field_name: str,
    row: sa.RowMapping,
) -> bytes:
    key_version = int(row["encryption_key_version"])
    value = EncryptedValue(
        ciphertext=bytes(row[f"{field_name}_ciphertext"]),
        nonce=bytes(row[f"{field_name}_nonce"]),
        tag=bytes(row[f"{field_name}_tag"]),
        key_version=key_version,
    )
    return cipher.decrypt(
        value,
        aad=encrypted_field_aad(
            table_name,
            record_id,
            field_name,
            key_version,
        ),
    )


def _add_encrypted_columns(
    table_name: str,
    field_names: tuple[str, ...],
) -> None:
    for field_name in field_names:
        op.add_column(
            table_name,
            sa.Column(f"{field_name}_ciphertext", sa.LargeBinary(), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column(f"{field_name}_nonce", sa.LargeBinary(length=12), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column(f"{field_name}_tag", sa.LargeBinary(length=16), nullable=True),
        )
    op.add_column(
        table_name,
        sa.Column(
            "encryption_key_version",
            sa.SmallInteger(),
            nullable=False,
            server_default=str(CURRENT_DATA_KEY_VERSION),
        ),
    )


def _make_encrypted_columns_required(
    table_name: str,
    field_names: tuple[str, ...],
) -> None:
    for field_name in field_names:
        op.alter_column(table_name, f"{field_name}_ciphertext", nullable=False)
        op.alter_column(table_name, f"{field_name}_nonce", nullable=False)
        op.alter_column(table_name, f"{field_name}_tag", nullable=False)
    op.alter_column(table_name, "encryption_key_version", server_default=None)


def upgrade() -> None:
    cipher = _cipher()
    bind = op.get_bind()

    op.rename_table("space_members", "space_memberships")
    op.execute("ALTER INDEX ix_space_members_user_id RENAME TO ix_space_memberships_user_id")
    op.execute(
        "ALTER TABLE space_memberships RENAME CONSTRAINT pk_space_members TO pk_space_memberships"
    )
    op.execute(
        "ALTER TABLE space_memberships "
        "RENAME CONSTRAINT fk_space_members_space_id_spaces "
        "TO fk_space_memberships_space_id_spaces"
    )
    op.execute(
        "ALTER TABLE space_memberships "
        "RENAME CONSTRAINT fk_space_members_user_id_users "
        "TO fk_space_memberships_user_id_users"
    )
    op.add_column(
        "space_memberships",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.alter_column("space_memberships", "created_at", server_default=None)
    op.create_check_constraint(
        op.f("ck_space_memberships_role_valid"),
        "space_memberships",
        "role IN ('owner', 'admin', 'member')",
    )

    _add_encrypted_columns("tasks", ("title", "description"))
    _add_encrypted_columns("pages", ("title", "content", "markdown"))
    _add_encrypted_columns("uploads", ("original_name",))

    tasks = sa.table(
        "tasks",
        sa.column("id", sa.Uuid()),
        sa.column("title", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("title_ciphertext", sa.LargeBinary()),
        sa.column("title_nonce", sa.LargeBinary()),
        sa.column("title_tag", sa.LargeBinary()),
        sa.column("description_ciphertext", sa.LargeBinary()),
        sa.column("description_nonce", sa.LargeBinary()),
        sa.column("description_tag", sa.LargeBinary()),
    )
    for row in bind.execute(sa.select(tasks.c.id, tasks.c.title, tasks.c.description)).mappings():
        values = _encrypt(
            cipher,
            table_name="tasks",
            record_id=row["id"],
            field_name="title",
            plaintext=row["title"].encode(),
        )
        values.update(
            _encrypt(
                cipher,
                table_name="tasks",
                record_id=row["id"],
                field_name="description",
                plaintext=row["description"].encode(),
            )
        )
        bind.execute(sa.update(tasks).where(tasks.c.id == row["id"]).values(**values))

    pages = sa.table(
        "pages",
        sa.column("id", sa.Uuid()),
        sa.column("title", sa.String()),
        sa.column("content", postgresql.JSONB()),
        sa.column("markdown", sa.Text()),
        sa.column("title_ciphertext", sa.LargeBinary()),
        sa.column("title_nonce", sa.LargeBinary()),
        sa.column("title_tag", sa.LargeBinary()),
        sa.column("content_ciphertext", sa.LargeBinary()),
        sa.column("content_nonce", sa.LargeBinary()),
        sa.column("content_tag", sa.LargeBinary()),
        sa.column("markdown_ciphertext", sa.LargeBinary()),
        sa.column("markdown_nonce", sa.LargeBinary()),
        sa.column("markdown_tag", sa.LargeBinary()),
    )
    for row in bind.execute(
        sa.select(
            pages.c.id,
            pages.c.title,
            pages.c.content,
            pages.c.markdown,
        )
    ).mappings():
        serialized_content = json.dumps(
            row["content"],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        values = _encrypt(
            cipher,
            table_name="pages",
            record_id=row["id"],
            field_name="title",
            plaintext=row["title"].encode(),
        )
        values.update(
            _encrypt(
                cipher,
                table_name="pages",
                record_id=row["id"],
                field_name="content",
                plaintext=serialized_content,
            )
        )
        values.update(
            _encrypt(
                cipher,
                table_name="pages",
                record_id=row["id"],
                field_name="markdown",
                plaintext=row["markdown"].encode(),
            )
        )
        bind.execute(sa.update(pages).where(pages.c.id == row["id"]).values(**values))

    uploads = sa.table(
        "uploads",
        sa.column("id", sa.Uuid()),
        sa.column("original_name", sa.String()),
        sa.column("original_name_ciphertext", sa.LargeBinary()),
        sa.column("original_name_nonce", sa.LargeBinary()),
        sa.column("original_name_tag", sa.LargeBinary()),
    )
    for row in bind.execute(sa.select(uploads.c.id, uploads.c.original_name)).mappings():
        values = _encrypt(
            cipher,
            table_name="uploads",
            record_id=row["id"],
            field_name="original_name",
            plaintext=row["original_name"].encode(),
        )
        bind.execute(sa.update(uploads).where(uploads.c.id == row["id"]).values(**values))

    _make_encrypted_columns_required("tasks", ("title", "description"))
    _make_encrypted_columns_required("pages", ("title", "content", "markdown"))
    _make_encrypted_columns_required("uploads", ("original_name",))

    op.drop_constraint(op.f("ck_tasks_title_length"), "tasks", type_="check")
    op.drop_constraint(op.f("ck_tasks_description_length"), "tasks", type_="check")
    op.drop_constraint(op.f("ck_pages_title_length"), "pages", type_="check")
    op.drop_constraint(op.f("ck_pages_markdown_length"), "pages", type_="check")

    op.drop_column("tasks", "title")
    op.drop_column("tasks", "description")
    op.drop_column("pages", "title")
    op.drop_column("pages", "content")
    op.drop_column("pages", "markdown")
    op.drop_column("uploads", "original_name")


def downgrade() -> None:
    cipher = _cipher()
    bind = op.get_bind()

    op.add_column("tasks", sa.Column("title", sa.String(length=200), nullable=True))
    op.add_column("tasks", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("pages", sa.Column("title", sa.String(length=200), nullable=True))
    op.add_column(
        "pages",
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column("pages", sa.Column("markdown", sa.Text(), nullable=True))
    op.add_column(
        "uploads",
        sa.Column("original_name", sa.String(length=255), nullable=True),
    )

    tasks = sa.table(
        "tasks",
        sa.column("id", sa.Uuid()),
        sa.column("title", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("title_ciphertext", sa.LargeBinary()),
        sa.column("title_nonce", sa.LargeBinary()),
        sa.column("title_tag", sa.LargeBinary()),
        sa.column("description_ciphertext", sa.LargeBinary()),
        sa.column("description_nonce", sa.LargeBinary()),
        sa.column("description_tag", sa.LargeBinary()),
        sa.column("encryption_key_version", sa.SmallInteger()),
    )
    for row in bind.execute(sa.select(tasks)).mappings():
        title = _decrypt(
            cipher,
            table_name="tasks",
            record_id=row["id"],
            field_name="title",
            row=row,
        ).decode()
        description = _decrypt(
            cipher,
            table_name="tasks",
            record_id=row["id"],
            field_name="description",
            row=row,
        ).decode()
        bind.execute(
            sa.update(tasks)
            .where(tasks.c.id == row["id"])
            .values(title=title, description=description)
        )

    pages = sa.table(
        "pages",
        sa.column("id", sa.Uuid()),
        sa.column("title", sa.String()),
        sa.column("content", postgresql.JSONB()),
        sa.column("markdown", sa.Text()),
        sa.column("title_ciphertext", sa.LargeBinary()),
        sa.column("title_nonce", sa.LargeBinary()),
        sa.column("title_tag", sa.LargeBinary()),
        sa.column("content_ciphertext", sa.LargeBinary()),
        sa.column("content_nonce", sa.LargeBinary()),
        sa.column("content_tag", sa.LargeBinary()),
        sa.column("markdown_ciphertext", sa.LargeBinary()),
        sa.column("markdown_nonce", sa.LargeBinary()),
        sa.column("markdown_tag", sa.LargeBinary()),
        sa.column("encryption_key_version", sa.SmallInteger()),
    )
    for row in bind.execute(sa.select(pages)).mappings():
        title = _decrypt(
            cipher,
            table_name="pages",
            record_id=row["id"],
            field_name="title",
            row=row,
        ).decode()
        content = json.loads(
            _decrypt(
                cipher,
                table_name="pages",
                record_id=row["id"],
                field_name="content",
                row=row,
            )
        )
        markdown = _decrypt(
            cipher,
            table_name="pages",
            record_id=row["id"],
            field_name="markdown",
            row=row,
        ).decode()
        bind.execute(
            sa.update(pages)
            .where(pages.c.id == row["id"])
            .values(title=title, content=content, markdown=markdown)
        )

    uploads = sa.table(
        "uploads",
        sa.column("id", sa.Uuid()),
        sa.column("original_name", sa.String()),
        sa.column("original_name_ciphertext", sa.LargeBinary()),
        sa.column("original_name_nonce", sa.LargeBinary()),
        sa.column("original_name_tag", sa.LargeBinary()),
        sa.column("encryption_key_version", sa.SmallInteger()),
    )
    for row in bind.execute(sa.select(uploads)).mappings():
        original_name = _decrypt(
            cipher,
            table_name="uploads",
            record_id=row["id"],
            field_name="original_name",
            row=row,
        ).decode()
        bind.execute(
            sa.update(uploads).where(uploads.c.id == row["id"]).values(original_name=original_name)
        )

    op.alter_column("tasks", "title", nullable=False)
    op.alter_column("tasks", "description", nullable=False)
    op.alter_column("pages", "title", nullable=False)
    op.alter_column("pages", "content", nullable=False)
    op.alter_column("pages", "markdown", nullable=False)
    op.alter_column("uploads", "original_name", nullable=False)

    op.create_check_constraint(
        op.f("ck_tasks_title_length"),
        "tasks",
        "char_length(title) BETWEEN 1 AND 200",
    )
    op.create_check_constraint(
        op.f("ck_tasks_description_length"),
        "tasks",
        "char_length(description) <= 5000",
    )
    op.create_check_constraint(
        op.f("ck_pages_title_length"),
        "pages",
        "char_length(title) BETWEEN 1 AND 200",
    )
    op.create_check_constraint(
        op.f("ck_pages_markdown_length"),
        "pages",
        "char_length(markdown) <= 200000",
    )

    for table_name, field_names in (
        ("tasks", ("title", "description")),
        ("pages", ("title", "content", "markdown")),
        ("uploads", ("original_name",)),
    ):
        for field_name in field_names:
            op.drop_column(table_name, f"{field_name}_tag")
            op.drop_column(table_name, f"{field_name}_nonce")
            op.drop_column(table_name, f"{field_name}_ciphertext")
        op.drop_column(table_name, "encryption_key_version")

    op.drop_constraint(
        op.f("ck_space_memberships_role_valid"),
        "space_memberships",
        type_="check",
    )
    op.drop_column("space_memberships", "created_at")
    op.execute(
        "ALTER TABLE space_memberships "
        "RENAME CONSTRAINT fk_space_memberships_user_id_users "
        "TO fk_space_members_user_id_users"
    )
    op.execute(
        "ALTER TABLE space_memberships "
        "RENAME CONSTRAINT fk_space_memberships_space_id_spaces "
        "TO fk_space_members_space_id_spaces"
    )
    op.execute(
        "ALTER TABLE space_memberships RENAME CONSTRAINT pk_space_memberships TO pk_space_members"
    )
    op.execute("ALTER INDEX ix_space_memberships_user_id RENAME TO ix_space_members_user_id")
    op.rename_table("space_memberships", "space_members")
