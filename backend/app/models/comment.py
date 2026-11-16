from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, LargeBinary, SmallInteger, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.issues import Task
    from app.models.user import User


class Comment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "task_comments"
    __table_args__ = (
        CheckConstraint("encryption_key_version = 1", name="encryption_key_version_valid"),
        CheckConstraint(
            "length(body_nonce) = 12 AND length(body_tag) = 16",
            name="encryption_metadata_lengths",
        ),
    )

    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    created_by_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    body_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    body_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    body_tag: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    encryption_key_version: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        nullable=False,
    )

    task: Mapped[Task] = relationship()
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
