from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.issues import IssueBoard
    from app.models.page import Page
    from app.models.user import User


class Space(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "spaces"
    __table_args__ = (CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="name_length"),)

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_by_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    trash_retention_days: Mapped[int] = mapped_column(default=7, server_default="7", nullable=False)

    members: Mapped[list[SpaceMember]] = relationship(
        back_populates="space",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    teams: Mapped[list[Team]] = relationship(
        back_populates="space",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Team.created_at",
    )


class SpaceMember(Base):
    __tablename__ = "space_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="role_valid",
        ),
    )

    space_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    space: Mapped[Space] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="space_memberships")


class Team(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("space_id", "name", name="uq_teams_space_name"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="name_length"),
    )

    space_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_by_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    space: Mapped[Space] = relationship(back_populates="teams")
    members: Mapped[list[TeamMember]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    issue_boards: Mapped[list[IssueBoard]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="IssueBoard.created_at",
    )
    pages: Mapped[list[Page]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Page.created_at",
    )


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="role_valid",
        ),
    )

    team_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)

    team: Mapped[Team] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="team_memberships")
