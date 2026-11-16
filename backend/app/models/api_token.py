from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class ApiToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "api_tokens"
    __table_args__ = (
        CheckConstraint("length(name) BETWEEN 1 AND 80", name="name_length"),
        CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
        CheckConstraint("length(token_prefix) = 17", name="token_prefix_length"),
        CheckConstraint("scopes IN ('read', 'read,write')", name="scopes_valid"),
        CheckConstraint("auth_version >= 0", name="auth_version_nonnegative"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    token_prefix: Mapped[str] = mapped_column(String(17), nullable=False)
    scopes: Mapped[str] = mapped_column(String(32), nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="api_tokens")
