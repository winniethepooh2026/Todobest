from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Space, SpaceMember, Team, TeamMember, User

SpaceRole = Literal["owner", "admin", "member"]
TeamRole = Literal["owner", "admin", "member"]

SPACE_ROLES: frozenset[str] = frozenset({"owner", "admin", "member"})
SPACE_MANAGER_ROLES: frozenset[str] = frozenset({"owner", "admin"})
TEAM_ROLES: frozenset[str] = frozenset({"owner", "admin", "member"})
TEAM_MANAGER_ROLES: frozenset[str] = frozenset({"owner", "admin"})
TASK_ADMIN_UPDATE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "assignee_id",
        "deadline",
        "status_id",
        "priority",
        "estimate",
        "parent_task_id",
        "label_ids",
    }
)


@dataclass(slots=True)
class TeamActorContext:
    team: Team
    space_membership: SpaceMember
    team_membership: TeamMember | None

    @property
    def can_access(self) -> bool:
        return self.space_membership.role in SPACE_MANAGER_ROLES or self.team_membership is not None

    @property
    def can_manage_members(self) -> bool:
        return self.space_membership.role in SPACE_MANAGER_ROLES or (
            self.team_membership is not None and self.team_membership.role in TEAM_MANAGER_ROLES
        )

    @property
    def can_manage_resources(self) -> bool:
        return self.space_membership.role in SPACE_MANAGER_ROLES or (
            self.team_membership is not None and self.team_membership.role in TEAM_MANAGER_ROLES
        )

    @property
    def can_manage_owner_role(self) -> bool:
        return self.space_membership.role == "owner" or (
            self.team_membership is not None and self.team_membership.role == "owner"
        )


# Space memberships


def can_manage_space_members(role: str) -> bool:
    return role in SPACE_MANAGER_ROLES


def ensure_role_allowed(role: str) -> None:
    if role not in SPACE_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown Space role")


def ensure_can_manage_members(actor_role: str) -> None:
    if not can_manage_space_members(actor_role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a Space owner or admin can manage members",
        )


def ensure_can_assign_role(
    *,
    actor_role: str,
    new_role: str,
    target_role: str | None = None,
) -> None:
    ensure_can_manage_members(actor_role)
    ensure_role_allowed(new_role)
    if actor_role != "owner" and (new_role == "owner" or target_role == "owner"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a Space owner can manage the owner role",
        )


def ensure_owner_survives(
    *,
    target_role: str,
    resulting_role: str | None,
    owner_count: int,
) -> None:
    removes_owner = target_role == "owner" and resulting_role != "owner"
    if removes_owner and owner_count <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The last Space owner cannot be removed or demoted",
        )


async def get_space_membership(
    db: AsyncSession,
    *,
    space_id: UUID,
    user_id: UUID,
) -> SpaceMember:
    membership = await db.scalar(
        select(SpaceMember)
        .join(Space, Space.id == SpaceMember.space_id)
        .where(
            SpaceMember.space_id == space_id,
            SpaceMember.user_id == user_id,
            Space.deleted_at.is_(None),
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    return membership


async def require_space_role(
    db: AsyncSession,
    *,
    space_id: UUID,
    user_id: UUID,
    roles: Collection[str],
) -> SpaceMember:
    membership = await get_space_membership(
        db,
        space_id=space_id,
        user_id=user_id,
    )
    if membership.role not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient Space permissions")
    return membership


# Team memberships


def ensure_team_role_allowed(role: str) -> None:
    if role not in TEAM_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown Team role")


def ensure_can_manage_team_members(context: TeamActorContext) -> None:
    if not context.can_manage_members:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a Team owner/admin or Space owner/admin can manage Team members",
        )


def ensure_can_manage_team_resources(
    context: TeamActorContext,
    *,
    detail: str = "Only a Team owner/admin or Space owner/admin can perform this action",
) -> None:
    if not context.can_manage_resources:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail)


def get_allowed_task_update_fields(
    context: TeamActorContext,
    *,
    user_id: UUID | None = None,
    created_by_id: UUID | None = None,
    assignee_id: UUID | None = None,
) -> frozenset[str]:
    if context.can_manage_resources:
        return TASK_ADMIN_UPDATE_FIELDS
    if (
        context.team_membership is not None
        and user_id is not None
        and user_id in {created_by_id, assignee_id}
    ):
        return frozenset({"title", "description", "deadline", "status_id"})
    return frozenset()


def validate_task_update_permissions(
    context: TeamActorContext,
    changed_fields: Collection[str],
    user_id: UUID | None = None,
    created_by_id: UUID | None = None,
    assignee_id: UUID | None = None,
) -> None:
    forbidden_fields = set(changed_fields) - get_allowed_task_update_fields(
        context,
        user_id=user_id,
        created_by_id=created_by_id,
        assignee_id=assignee_id,
    )
    if forbidden_fields:
        fields = ", ".join(sorted(forbidden_fields))
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Insufficient permissions to update task fields: {fields}",
        )


def ensure_can_change_task_status(
    context: TeamActorContext,
    *,
    user_id: UUID,
    assignee_id: UUID | None,
) -> None:
    if context.can_manage_resources:
        return
    if context.team_membership is None or assignee_id != user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Members can change the status only of tasks assigned to themselves",
        )


def can_edit_page(
    context: TeamActorContext,
    *,
    user_id: UUID,
    created_by_id: UUID,
) -> bool:
    return context.can_manage_resources or created_by_id == user_id


def ensure_can_edit_page(
    context: TeamActorContext,
    *,
    user_id: UUID,
    created_by_id: UUID,
) -> None:
    if not can_edit_page(
        context,
        user_id=user_id,
        created_by_id=created_by_id,
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Members can modify only Pages they created",
        )


def ensure_can_assign_team_role(
    *,
    context: TeamActorContext,
    new_role: str,
    target_role: str | None = None,
) -> None:
    ensure_can_manage_team_members(context)
    ensure_team_role_allowed(new_role)
    if not context.can_manage_owner_role and (new_role == "owner" or target_role == "owner"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a Team owner or Space owner can manage the Team owner role",
        )


def ensure_team_owner_survives(
    *,
    target_role: str,
    resulting_role: str | None,
    owner_count: int,
) -> None:
    removes_owner = target_role == "owner" and resulting_role != "owner"
    if removes_owner and owner_count <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The last Team owner cannot be removed or demoted",
        )


async def get_team_actor_context(
    db: AsyncSession,
    *,
    team_id: UUID,
    user_id: UUID,
    for_update: bool = False,
) -> TeamActorContext:
    team = await db.scalar(
        select(Team)
        .join(Space, Space.id == Team.space_id)
        .where(
            Team.id == team_id,
            Team.deleted_at.is_(None),
            Space.deleted_at.is_(None),
        )
    )
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")

    if for_update:
        # Keep the same lock order as Space-member removal: parent Space first,
        # then Team. This prevents a concurrent Space removal from racing a
        # Team-membership change.
        parent_space_id = await db.scalar(
            select(Space.id)
            .where(Space.id == team.space_id, Space.deleted_at.is_(None))
            .with_for_update()
        )
        if parent_space_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
        team = await db.scalar(
            select(Team)
            .where(Team.id == team_id, Team.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")

    space_membership = await db.get(SpaceMember, (team.space_id, user_id))
    if space_membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")

    team_membership = await db.get(TeamMember, (team_id, user_id))
    context = TeamActorContext(
        team=team,
        space_membership=space_membership,
        team_membership=team_membership,
    )
    if not context.can_access:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    return context


async def require_direct_team_member(
    db: AsyncSession,
    *,
    team_id: UUID,
    user_id: UUID,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    detail: str = "User must be a Team member",
) -> TeamMember:
    membership = await db.scalar(
        select(TeamMember)
        .join(Team, Team.id == TeamMember.team_id)
        .join(
            SpaceMember,
            and_(
                SpaceMember.space_id == Team.space_id,
                SpaceMember.user_id == TeamMember.user_id,
            ),
        )
        .join(User, User.id == TeamMember.user_id)
        .where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user_id,
            User.is_active.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(status_code, detail)
    return membership
