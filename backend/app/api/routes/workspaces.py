from __future__ import annotations

import json
import secrets
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, selectinload

from app.api.deps import (
    CSRF,
    CurrentUser,
    DBSession,
    RedisClient,
    enforce_mail_recipient_rate_limit,
    enforce_rate_limit,
)
from app.core.config import settings
from app.models import (
    Invitation,
    IssueBoard,
    Space,
    SpaceMember,
    Task,
    Team,
    TeamMember,
    User,
)
from app.schemas import (
    Message,
    NavigationSpace,
    SpaceCreate,
    SpaceMemberCreate,
    SpaceMemberOut,
    SpaceMembersOut,
    SpaceMemberUpdate,
    SpaceOut,
    SpaceUpdate,
    TeamCreate,
    TeamMemberCreate,
    TeamMemberOut,
    TeamMembersOut,
    TeamMemberUpdate,
    TeamOut,
    TeamUpdate,
)
from app.schemas.navigation import NavigationBoard, NavigationPage, NavigationTeam
from app.services.access import (
    SPACE_WIDE_TEAM_ROLES,
    get_space_for_user,
    get_team_for_user,
)
from app.services.avatars import user_avatar_url
from app.services.content_encryption import get_page_title
from app.services.mail import enqueue_mail
from app.services.memberships import (
    SPACE_MANAGER_ROLES,
    can_manage_space_members,
    ensure_can_assign_role,
    ensure_can_assign_team_role,
    ensure_can_manage_members,
    ensure_can_manage_team_members,
    ensure_owner_survives,
    ensure_team_owner_survives,
    get_space_membership,
    get_team_actor_context,
    require_space_role,
)
from app.services.one_time_tokens import hash_token

router = APIRouter(tags=["Workspaces"])


def membership_to_schema(membership: SpaceMember) -> SpaceMemberOut:
    return SpaceMemberOut(
        user_id=membership.user_id,
        email=membership.user.email,
        name=membership.user.name,
        avatar_url=user_avatar_url(membership.user),
        role=membership.role,
        created_at=membership.created_at,
    )


def team_membership_to_schema(membership: TeamMember) -> TeamMemberOut:
    return TeamMemberOut(
        user_id=membership.user_id,
        email=membership.user.email,
        name=membership.user.name,
        avatar_url=user_avatar_url(membership.user),
        is_active=membership.user.is_active,
        role=membership.role,
    )


@router.get("/spaces", response_model=list[SpaceOut])
async def list_spaces(current_user: CurrentUser, db: DBSession) -> list[Space]:
    result = await db.scalars(
        select(Space)
        .join(SpaceMember, SpaceMember.space_id == Space.id)
        .where(SpaceMember.user_id == current_user.id, Space.deleted_at.is_(None))
        .order_by(Space.created_at)
    )
    return list(result)


@router.post("/spaces", response_model=SpaceOut, status_code=status.HTTP_201_CREATED)
async def create_space(
    payload: SpaceCreate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Space:
    space = Space(
        name=payload.name,
        created_by_id=current_user.id,
        owner_user_id=current_user.id,
    )
    space.members.append(SpaceMember(user_id=current_user.id, role="owner"))
    db.add(space)
    await db.commit()
    await db.refresh(space)
    return space


@router.get("/spaces/{space_id}", response_model=SpaceOut)
async def get_space(
    space_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> Space:
    return await get_space_for_user(db, space_id, current_user.id)


@router.patch("/spaces/{space_id}", response_model=SpaceOut)
async def update_space(
    space_id: UUID,
    payload: SpaceUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Space:
    space = await db.scalar(select(Space).where(Space.id == space_id).with_for_update())
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    await require_space_role(
        db,
        space_id=space_id,
        user_id=current_user.id,
        roles=SPACE_MANAGER_ROLES,
    )
    space.name = payload.name
    await db.commit()
    return space


@router.get("/spaces/{space_id}/members", response_model=SpaceMembersOut)
async def list_space_members(
    space_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> SpaceMembersOut:
    actor = await get_space_membership(
        db,
        space_id=space_id,
        user_id=current_user.id,
    )
    memberships = list(
        await db.scalars(
            select(SpaceMember)
            .where(SpaceMember.space_id == space_id)
            .options(selectinload(SpaceMember.user))
            .order_by(
                case(
                    (SpaceMember.role == "owner", 0),
                    (SpaceMember.role == "admin", 1),
                    else_=2,
                ),
                SpaceMember.created_at,
            )
        )
    )
    return SpaceMembersOut(
        current_user_role=actor.role,
        can_manage_members=can_manage_space_members(actor.role),
        members=[membership_to_schema(membership) for membership in memberships],
    )


@router.post(
    "/spaces/{space_id}/members",
    response_model=Message,
    status_code=status.HTTP_201_CREATED,
)
async def add_space_member(
    space_id: UUID,
    payload: SpaceMemberCreate,
    current_user: CurrentUser,
    db: DBSession,
    redis: RedisClient,
    _: CSRF,
) -> Message:
    space = await db.scalar(select(Space).where(Space.id == space_id).with_for_update())
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")

    actor = await get_space_membership(
        db,
        space_id=space_id,
        user_id=current_user.id,
    )
    ensure_can_assign_role(actor_role=actor.role, new_role=payload.role)
    await enforce_rate_limit(
        redis,
        scope="invitation-mail-actor",
        identifier=str(current_user.id),
        limit=settings.invitation_mail_actor_rate_limit_attempts,
        window_seconds=settings.mail_rate_limit_window_seconds,
    )
    await enforce_mail_recipient_rate_limit(
        redis,
        recipient=payload.email,
        purpose="invitation",
    )

    duplicate = await db.scalar(
        select(Invitation.id).where(
            Invitation.space_id == space_id,
            Invitation.team_id.is_(None),
            Invitation.email == payload.email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > datetime.now(UTC),
        )
    )
    if duplicate is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An active invitation already exists")

    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation(
        space_id=space_id,
        email=payload.email,
        token_hash=hash_token(raw_token),
        role=payload.role,
        invited_by_id=current_user.id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.invitation_ttl_days),
    )
    db.add(invitation)
    await db.commit()
    enqueue_mail(
        recipient=payload.email,
        kind="invitation",
        context={
            "target_name": space.name,
            "action_url": f"{settings.frontend_url}/invite?token={raw_token}",
        },
        idempotency_key=f"invitation/{invitation.id}",
    )
    return Message(message="If the address can be invited, an invitation was sent")


@router.patch(
    "/spaces/{space_id}/members/{user_id}",
    response_model=SpaceMemberOut,
)
async def update_space_member(
    space_id: UUID,
    user_id: UUID,
    payload: SpaceMemberUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> SpaceMemberOut:
    space = await db.scalar(select(Space).where(Space.id == space_id).with_for_update())
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")

    actor = await get_space_membership(
        db,
        space_id=space_id,
        user_id=current_user.id,
    )
    target = await db.scalar(
        select(SpaceMember)
        .where(
            SpaceMember.space_id == space_id,
            SpaceMember.user_id == user_id,
        )
        .options(selectinload(SpaceMember.user))
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space member not found")

    ensure_can_assign_role(
        actor_role=actor.role,
        target_role=target.role,
        new_role=payload.role,
    )
    owner_count = int(
        await db.scalar(
            select(func.count())
            .select_from(SpaceMember)
            .where(
                SpaceMember.space_id == space_id,
                SpaceMember.role == "owner",
            )
        )
        or 0
    )
    ensure_owner_survives(
        target_role=target.role,
        resulting_role=payload.role,
        owner_count=owner_count,
    )

    target.role = payload.role
    await db.commit()
    return membership_to_schema(target)


@router.delete(
    "/spaces/{space_id}/members/{user_id}",
    response_model=Message,
)
async def remove_space_member(
    space_id: UUID,
    user_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    space = await db.scalar(select(Space).where(Space.id == space_id).with_for_update())
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")

    actor = await get_space_membership(
        db,
        space_id=space_id,
        user_id=current_user.id,
    )
    target = await db.get(SpaceMember, (space_id, user_id))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space member not found")

    ensure_can_manage_members(actor.role)
    ensure_can_assign_role(
        actor_role=actor.role,
        target_role=target.role,
        new_role="member",
    )
    owner_count = int(
        await db.scalar(
            select(func.count())
            .select_from(SpaceMember)
            .where(
                SpaceMember.space_id == space_id,
                SpaceMember.role == "owner",
            )
        )
        or 0
    )
    ensure_owner_survives(
        target_role=target.role,
        resulting_role=None,
        owner_count=owner_count,
    )

    locked_team_ids = list(
        await db.scalars(
            select(Team.id).where(Team.space_id == space_id).order_by(Team.id).with_for_update()
        )
    )
    team_ids = select(Team.id).where(Team.space_id == space_id)
    other_owner = aliased(TeamMember)
    last_owned_team_id = await db.scalar(
        select(TeamMember.team_id).where(
            TeamMember.user_id == user_id,
            TeamMember.role == "owner",
            TeamMember.team_id.in_(locked_team_ids),
            ~select(other_owner.user_id)
            .where(
                other_owner.team_id == TeamMember.team_id,
                other_owner.role == "owner",
                other_owner.user_id != user_id,
            )
            .exists(),
        )
    )
    if last_owned_team_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Transfer ownership of every Team before removing this Space member",
        )

    board_ids = select(IssueBoard.id).where(IssueBoard.team_id.in_(locked_team_ids))
    await db.execute(
        update(Task)
        .where(Task.assignee_id == user_id, Task.board_id.in_(board_ids))
        .values(assignee_id=None)
    )
    await db.execute(
        delete(TeamMember).where(
            TeamMember.user_id == user_id,
            TeamMember.team_id.in_(team_ids),
        )
    )
    await db.delete(target)
    await db.commit()
    return Message(message="Space member removed")


@router.get("/spaces/{space_id}/teams", response_model=list[TeamOut])
async def list_teams(
    space_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> list[Team]:
    membership = await get_space_membership(
        db,
        space_id=space_id,
        user_id=current_user.id,
    )
    query = select(Team).where(Team.space_id == space_id, Team.deleted_at.is_(None))
    if membership.role not in SPACE_WIDE_TEAM_ROLES:
        query = query.join(TeamMember, TeamMember.team_id == Team.id).where(
            TeamMember.user_id == current_user.id
        )
    result = await db.scalars(query.order_by(Team.created_at))
    return list(result)


@router.post(
    "/spaces/{space_id}/teams",
    response_model=TeamOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_team(
    space_id: UUID,
    payload: TeamCreate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Team:
    # Serialize against Space-member removal before checking membership. The
    # same parent-first lock order is used by the removal path.
    space = await db.scalar(select(Space).where(Space.id == space_id).with_for_update())
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    await require_space_role(
        db,
        space_id=space_id,
        user_id=current_user.id,
        roles=SPACE_MANAGER_ROLES,
    )
    team = Team(
        space_id=space_id,
        name=payload.name,
        created_by_id=current_user.id,
    )
    team.members.append(TeamMember(user_id=current_user.id, role="owner"))
    db.add(team)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A team with this name already exists in the Space",
        ) from exc
    await db.refresh(team)
    return team


@router.get("/teams/{team_id}", response_model=TeamOut)
async def get_team(
    team_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> Team:
    return await get_team_for_user(db, team_id, current_user.id)


@router.patch("/teams/{team_id}", response_model=TeamOut)
async def update_team(
    team_id: UUID,
    payload: TeamUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Team:
    context = await get_team_actor_context(
        db,
        team_id=team_id,
        user_id=current_user.id,
        for_update=True,
    )
    ensure_can_manage_team_members(context)
    team = context.team
    team.name = payload.name
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Team name is already used") from exc
    return team


@router.get("/teams/{team_id}/members", response_model=TeamMembersOut)
async def list_team_members(
    team_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> TeamMembersOut:
    context = await get_team_actor_context(
        db,
        team_id=team_id,
        user_id=current_user.id,
    )
    memberships = list(
        await db.scalars(
            select(TeamMember)
            .join(User, User.id == TeamMember.user_id)
            .where(TeamMember.team_id == team_id)
            .options(selectinload(TeamMember.user))
            .order_by(
                case(
                    (TeamMember.role == "owner", 0),
                    (TeamMember.role == "admin", 1),
                    else_=2,
                ),
                User.name,
            )
        )
    )
    return TeamMembersOut(
        current_user_space_role=context.space_membership.role,
        current_user_team_role=(
            context.team_membership.role if context.team_membership is not None else None
        ),
        can_manage_members=context.can_manage_members,
        can_manage_owner_role=context.can_manage_owner_role,
        members=[team_membership_to_schema(membership) for membership in memberships],
    )


@router.post(
    "/teams/{team_id}/members",
    response_model=TeamMemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_team_member(
    team_id: UUID,
    payload: TeamMemberCreate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> TeamMemberOut:
    context = await get_team_actor_context(
        db,
        team_id=team_id,
        user_id=current_user.id,
        for_update=True,
    )
    ensure_can_assign_team_role(context=context, new_role=payload.role)

    space_membership = await db.get(
        SpaceMember,
        (context.team.space_id, payload.user_id),
    )
    if space_membership is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "User must be a member of the parent Space before joining the Team",
        )

    existing = await db.get(TeamMember, (team_id, payload.user_id))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "User is already a Team member")

    user = await db.get(User, payload.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    membership = TeamMember(
        team_id=team_id,
        user_id=payload.user_id,
        role=payload.role,
    )
    membership.user = user
    db.add(membership)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "User is already a Team member",
        ) from exc
    return team_membership_to_schema(membership)


@router.patch(
    "/teams/{team_id}/members/{user_id}",
    response_model=TeamMemberOut,
)
async def update_team_member(
    team_id: UUID,
    user_id: UUID,
    payload: TeamMemberUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> TeamMemberOut:
    context = await get_team_actor_context(
        db,
        team_id=team_id,
        user_id=current_user.id,
        for_update=True,
    )
    target = await db.scalar(
        select(TeamMember)
        .where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
        .options(selectinload(TeamMember.user))
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team member not found")

    ensure_can_assign_team_role(
        context=context,
        target_role=target.role,
        new_role=payload.role,
    )
    owner_count = int(
        await db.scalar(
            select(func.count())
            .select_from(TeamMember)
            .where(TeamMember.team_id == team_id, TeamMember.role == "owner")
        )
        or 0
    )
    ensure_team_owner_survives(
        target_role=target.role,
        resulting_role=payload.role,
        owner_count=owner_count,
    )

    target.role = payload.role
    await db.commit()
    return team_membership_to_schema(target)


@router.delete("/teams/{team_id}/members/{user_id}", response_model=Message)
async def remove_team_member(
    team_id: UUID,
    user_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    context = await get_team_actor_context(
        db,
        team_id=team_id,
        user_id=current_user.id,
        for_update=True,
    )
    target = await db.get(TeamMember, (team_id, user_id))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team member not found")

    ensure_can_assign_team_role(
        context=context,
        target_role=target.role,
        new_role="member",
    )
    owner_count = int(
        await db.scalar(
            select(func.count())
            .select_from(TeamMember)
            .where(TeamMember.team_id == team_id, TeamMember.role == "owner")
        )
        or 0
    )
    ensure_team_owner_survives(
        target_role=target.role,
        resulting_role=None,
        owner_count=owner_count,
    )

    board_ids = select(IssueBoard.id).where(IssueBoard.team_id == team_id)
    await db.execute(
        update(Task)
        .where(Task.assignee_id == user_id, Task.board_id.in_(board_ids))
        .values(assignee_id=None)
    )
    await db.delete(target)
    await db.commit()
    return Message(message="Team member removed")


@router.get("/navigation", response_model=list[NavigationSpace])
async def get_navigation(
    current_user: CurrentUser,
    db: DBSession,
    redis: RedisClient,
) -> list[NavigationSpace]:
    try:
        cache_version = await redis.get("navigation:structure-version") or "0"
    except RedisError:
        cache_version = "0"
    cache_key = f"navigation:v2:{cache_version}:{current_user.id}"
    try:
        cached = await redis.get(cache_key)
        if cached:
            return [NavigationSpace.model_validate(item) for item in json.loads(cached)]
    except (RedisError, ValueError, TypeError):
        pass
    space_rows = list(
        (
            await db.execute(
                select(Space, SpaceMember.role)
                .join(SpaceMember, SpaceMember.space_id == Space.id)
                .where(SpaceMember.user_id == current_user.id, Space.deleted_at.is_(None))
                .order_by(Space.created_at)
            )
        ).all()
    )
    teams = list(
        await db.scalars(
            select(Team)
            .join(Space, Space.id == Team.space_id)
            .join(SpaceMember, SpaceMember.space_id == Team.space_id)
            .outerjoin(
                TeamMember,
                and_(
                    TeamMember.team_id == Team.id,
                    TeamMember.user_id == current_user.id,
                ),
            )
            .where(
                SpaceMember.user_id == current_user.id,
                Space.deleted_at.is_(None),
                Team.deleted_at.is_(None),
                or_(
                    SpaceMember.role.in_(SPACE_WIDE_TEAM_ROLES),
                    TeamMember.user_id == current_user.id,
                ),
            )
            .options(
                selectinload(Team.issue_boards),
                selectinload(Team.pages),
            )
            .order_by(Team.created_at)
        )
    )

    teams_by_space: dict[UUID, list[Team]] = {}
    for team in teams:
        teams_by_space.setdefault(team.space_id, []).append(team)

    navigation = [
        NavigationSpace(
            id=space.id,
            name=space.name,
            role=role,
            teams=[
                NavigationTeam(
                    id=team.id,
                    name=team.name,
                    boards=[
                        NavigationBoard(
                            id=board.id,
                            name=board.name,
                            key=board.key,
                        )
                        for board in team.issue_boards
                        if board.deleted_at is None
                    ],
                    pages=[
                        NavigationPage(id=page.id, title=get_page_title(page))
                        for page in team.pages
                        if page.deleted_at is None
                    ],
                )
                for team in teams_by_space.get(space.id, [])
            ],
        )
        for space, role in space_rows
    ]
    with suppress(RedisError):
        await redis.set(
            cache_key,
            json.dumps([item.model_dump(mode="json") for item in navigation]),
            ex=60,
        )
    return navigation
