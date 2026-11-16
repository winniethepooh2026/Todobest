from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.page import Upload
    from app.models.user import User
    from app.models.workspace import Team


class IssueStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class IssueBoard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "issue_boards"
    __table_args__ = (
        UniqueConstraint("team_id", "key", name="uq_issue_boards_team_key"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 100", name="name_length"),
        CheckConstraint("key ~ '^[A-Z]{2,5}$'", name="key_format"),
        CheckConstraint("next_task_number > 0", name="next_task_number_positive"),
    )

    team_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(5), nullable=False)
    next_task_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    team: Mapped[Team] = relationship(back_populates="issue_boards")
    columns: Mapped[list[BoardColumn]] = relationship(
        back_populates="board",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BoardColumn.position",
    )
    tasks: Mapped[list[Task]] = relationship(
        back_populates="board",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Task.position",
    )


class BoardColumn(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "board_columns"
    __table_args__ = (
        UniqueConstraint("board_id", "position", name="uq_board_columns_board_position"),
        UniqueConstraint(
            "board_id",
            "system_status",
            name="uq_board_columns_board_system_status",
        ),
        Index(
            "uq_board_columns_board_default",
            "board_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
        CheckConstraint("char_length(name) BETWEEN 1 AND 40", name="name_length"),
        CheckConstraint(
            "system_status IS NULL OR system_status IN ('todo', 'in_progress', 'done')",
            name="system_status_valid",
        ),
        UniqueConstraint("id", "board_id", name="uq_board_columns_id_board_id"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint(
            "color IS NULL OR color ~ '^#[0-9a-fA-F]{6}$'",
            name="color_format",
        ),
    )

    board_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("issue_boards.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    system_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    board: Mapped[IssueBoard] = relationship(back_populates="columns")
    tasks: Mapped[list[Task]] = relationship(
        back_populates="status",
        foreign_keys="Task.status_id",
    )


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("board_id", "number", name="uq_tasks_board_number"),
        Index(
            "ix_tasks_board_status_position",
            "board_id",
            "status_id",
            "position",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_tasks_assignee_updated",
            "assignee_id",
            "updated_at",
            "id",
            postgresql_where=text("deleted_at IS NULL AND assignee_id IS NOT NULL"),
            sqlite_where=text("deleted_at IS NULL AND assignee_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["status_id", "board_id"],
            ["board_columns.id", "board_columns.board_id"],
            name="fk_tasks_status_board_columns",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("number > 0", name="number_positive"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint(
            "priority IN ('none', 'low', 'medium', 'high', 'urgent')",
            name="priority_valid",
        ),
        CheckConstraint("estimate IS NULL OR estimate >= 0", name="estimate_nonnegative"),
        CheckConstraint("encryption_key_version = 1", name="encryption_key_version_valid"),
        CheckConstraint(
            "length(title_nonce) = 12 AND length(title_tag) = 16 "
            "AND length(description_nonce) = 12 AND length(description_tag) = 16",
            name="encryption_metadata_lengths",
        ),
    )

    board_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("issue_boards.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "board_columns.id",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        index=True,
        nullable=False,
    )
    assignee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    created_by_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title_blind_index: Mapped[bytes | None] = mapped_column(LargeBinary(32), index=True)
    title_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
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
    priority: Mapped[str] = mapped_column(String(16), default="none", nullable=False, index=True)
    estimate: Mapped[int | None] = mapped_column(Integer)
    parent_task_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="SET NULL"),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    board: Mapped[IssueBoard] = relationship(back_populates="tasks")
    status: Mapped[BoardColumn] = relationship(
        back_populates="tasks",
        foreign_keys=[status_id],
    )
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    labels: Mapped[list[TaskLabel]] = relationship(
        secondary="task_label_links",
        lazy="noload",
    )
    attachments: Mapped[list[Upload]] = relationship(back_populates="task")


class TaskLabel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "task_labels"
    __table_args__ = (
        UniqueConstraint("board_id", "name", name="uq_task_labels_board_name"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 40", name="name_length"),
        CheckConstraint("color ~ '^#[0-9a-fA-F]{6}$'", name="color_format"),
    )

    board_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("issue_boards.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#71717a")


class TaskLabelLink(Base):
    __tablename__ = "task_label_links"
    __table_args__ = (UniqueConstraint("task_id", "label_id", name="uq_task_label_links"),)

    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    label_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("task_labels.id", ondelete="CASCADE"),
        primary_key=True,
    )


class TaskRelation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "task_relations"
    __table_args__ = (
        UniqueConstraint("source_task_id", "target_task_id", "kind", name="uq_task_relation"),
        CheckConstraint("source_task_id <> target_task_id", name="different_tasks"),
        CheckConstraint(
            "kind IN ('blocks', 'relates_to', 'duplicates')",
            name="kind_valid",
        ),
    )

    source_task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    target_task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)


class TaskActivity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "task_activities"

    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    field: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
