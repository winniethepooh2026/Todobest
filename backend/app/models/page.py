from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.issues import Task
    from app.models.user import User
    from app.models.workspace import Team


class Page(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pages"
    __table_args__ = (
        CheckConstraint("encryption_key_version = 1", name="encryption_key_version_valid"),
        CheckConstraint(
            "length(title_nonce) = 12 AND length(title_tag) = 16 "
            "AND length(content_nonce) = 12 AND length(content_tag) = 16 "
            "AND length(markdown_nonce) = 12 AND length(markdown_tag) = 16",
            name="encryption_metadata_lengths",
        ),
    )

    team_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    title_blind_index: Mapped[bytes | None] = mapped_column(LargeBinary(32), index=True)
    title_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    title_tag: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    content_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    content_tag: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    markdown_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    markdown_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    markdown_tag: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    encryption_key_version: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        nullable=False,
    )
    created_by_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    team: Mapped[Team] = relationship(back_populates="pages")
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    images: Mapped[list[Upload]] = relationship(back_populates="page")


class Upload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "uploads"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="positive_size"),
        CheckConstraint("width > 0 AND height > 0", name="positive_dimensions"),
        CheckConstraint("content_type = 'image/webp'", name="content_type_webp"),
        CheckConstraint("encryption_key_version = 1", name="encryption_key_version_valid"),
        CheckConstraint(
            "length(original_name_nonce) = 12 AND length(original_name_tag) = 16",
            name="encryption_metadata_lengths",
        ),
    )

    filename: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    original_name_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    original_name_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    original_name_tag: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    encryption_key_version: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        nullable=False,
    )
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    space_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        index=True,
    )
    page_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("pages.id", ondelete="SET NULL"),
        index=True,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="SET NULL"),
        index=True,
    )

    page: Mapped[Page | None] = relationship(back_populates="images")
    task: Mapped[Task | None] = relationship(back_populates="attachments")
