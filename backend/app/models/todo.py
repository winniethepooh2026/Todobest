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
    from app.models.user import User


class Todo(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "todos"
    __table_args__ = (
        CheckConstraint(
            "status IN ('todo', 'in_progress', 'done')",
            name="status_valid",
        ),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint("encryption_key_version = 1", name="encryption_key_version_valid"),
        CheckConstraint(
            "length(title_nonce) = 12 AND length(title_tag) = 16 "
            "AND length(description_nonce) = 12 AND length(description_tag) = 16",
            name="encryption_metadata_lengths",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    completed_by_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    title_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    title_blind_index: Mapped[bytes | None] = mapped_column(LargeBinary(32), index=True)
    title_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    title_tag: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    description_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    description_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    description_tag: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    encryption_key_version: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        nullable=False,
    )
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="todo")
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    completed_by: Mapped[User | None] = relationship(foreign_keys=[completed_by_id])
