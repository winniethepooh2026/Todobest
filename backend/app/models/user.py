from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.api_token import ApiToken
    from app.models.lifecycle import OneTimeToken
    from app.models.workspace import SpaceMember, TeamMember


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("auth_version >= 0", name="auth_version_nonnegative"),
        CheckConstraint(
            "(avatar_object_key IS NULL) = (avatar_content_hash IS NULL)",
            name="avatar_object_and_hash_together",
        ),
        CheckConstraint(
            "avatar_content_hash IS NULL OR length(avatar_content_hash) = 64",
            name="avatar_content_hash_length",
        ),
        CheckConstraint(
            "avatar_source_url_hash IS NULL OR length(avatar_source_url_hash) = 64",
            name="avatar_source_url_hash_length",
        ),
        CheckConstraint(
            "avatar_requested_source_hash IS NULL OR length(avatar_requested_source_hash) = 64",
            name="avatar_requested_source_hash_length",
        ),
        CheckConstraint(
            "avatar_import_generation >= 0",
            name="avatar_import_generation_nonnegative",
        ),
        UniqueConstraint("avatar_object_key", name="uq_users_avatar_object_key"),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    bio: Mapped[str | None] = mapped_column(String(280))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    avatar_object_key: Mapped[str | None] = mapped_column(String(255))
    avatar_content_hash: Mapped[str | None] = mapped_column(String(64))
    avatar_source_url_hash: Mapped[str | None] = mapped_column(String(64))
    avatar_requested_source_hash: Mapped[str | None] = mapped_column(String(64))
    avatar_import_generation: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    avatar_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(String(512))
    totp_pending_secret: Mapped[str | None] = mapped_column(String(512))
    totp_pending_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_last_counter: Mapped[int] = mapped_column(
        Integer, default=-1, server_default="-1", nullable=False
    )
    totp_recovery_hashes: Mapped[str | None] = mapped_column(String(2048))
    auth_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    api_tokens: Mapped[list[ApiToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    space_memberships: Mapped[list[SpaceMember]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    team_memberships: Mapped[list[TeamMember]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    one_time_tokens: Mapped[list[OneTimeToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class UserSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    refresh_jti: Mapped[UUID] = mapped_column(Uuid, unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="sessions")
