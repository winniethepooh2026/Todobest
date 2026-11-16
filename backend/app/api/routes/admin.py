from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import (
    CSRF,
    AdminStepUp,
    AdminUser,
    DBSession,
    RedisClient,
    enforce_rate_limit,
)
from app.core.config import settings
from app.core.security import (
    PasswordWorkCapacityError,
    create_admin_step_up_token,
    verify_password_async,
)
from app.models import (
    IssueBoard,
    Page,
    Space,
    SpaceMember,
    Task,
    Team,
    TeamMember,
    User,
    UserSession,
)
from app.schemas import (
    AdminFunnelOut,
    AdminFunnelStepOut,
    AdminOverviewOut,
    AdminRegistrationPointOut,
    AdminRegistrationsOut,
    AdminStepUpOut,
    AdminStepUpRequest,
    AdminUpdateUserRequest,
    AdminUserOut,
    AdminUsersPageOut,
)
from app.services.admin import set_platform_admin
from app.services.avatars import user_avatar_url
from app.services.mfa import verify_second_factor

router = APIRouter(prefix="/admin", tags=["Admin"])

DEFAULT_USERS_PAGE_LIMIT = 50
MAX_USERS_PAGE_LIMIT = 200


@router.post("/step-up", response_model=AdminStepUpOut)
async def create_admin_step_up(
    payload: AdminStepUpRequest,
    admin: AdminUser,
    db: DBSession,
    redis: RedisClient,
    _: CSRF,
) -> AdminStepUpOut:
    await enforce_rate_limit(
        redis,
        scope="admin-step-up",
        identifier=str(admin.id),
        limit=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    locked = await db.scalar(
        select(User)
        .where(User.id == admin.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    try:
        password_valid = (
            locked is not None
            and locked.password_hash is not None
            and (await verify_password_async(payload.password, locked.password_hash))
        )
    except PasswordWorkCapacityError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Password verification is busy"
        ) from exc
    if not password_valid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid admin password")
    if not locked.totp_secret:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Enable two-factor authentication in settings"
        )
    if not verify_second_factor(locked, payload.mfa_code):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid second factor")
    await db.commit()
    return AdminStepUpOut(token=create_admin_step_up_token(locked.id, locked.auth_version))


@router.get("/overview", response_model=AdminOverviewOut)
async def get_overview(_admin: AdminUser, db: DBSession) -> AdminOverviewOut:
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since_24h = now - timedelta(hours=24)
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    async def count(query) -> int:
        return await db.scalar(query) or 0

    return AdminOverviewOut(
        total_users=await count(select(func.count()).select_from(User)),
        new_users_today=await count(
            select(func.count()).select_from(User).where(User.created_at >= today_start)
        ),
        new_users_7d=await count(
            select(func.count()).select_from(User).where(User.created_at >= since_7d)
        ),
        new_users_30d=await count(
            select(func.count()).select_from(User).where(User.created_at >= since_30d)
        ),
        active_users_24h=await count(
            select(func.count(func.distinct(UserSession.user_id))).where(
                func.coalesce(UserSession.last_seen_at, UserSession.created_at) >= since_24h
            )
        ),
        active_users_7d=await count(
            select(func.count(func.distinct(UserSession.user_id))).where(
                func.coalesce(UserSession.last_seen_at, UserSession.created_at) >= since_7d
            )
        ),
        active_users_30d=await count(
            select(func.count(func.distinct(UserSession.user_id))).where(
                func.coalesce(UserSession.last_seen_at, UserSession.created_at) >= since_30d
            )
        ),
        total_spaces=await count(select(func.count()).select_from(Space)),
        total_teams=await count(select(func.count()).select_from(Team)),
        total_boards=await count(select(func.count()).select_from(IssueBoard)),
        total_pages=await count(select(func.count()).select_from(Page)),
        total_tasks=await count(select(func.count()).select_from(Task)),
    )


@router.get("/users", response_model=AdminUsersPageOut)
async def list_users(
    _admin: AdminUser,
    db: DBSession,
    limit: int = Query(DEFAULT_USERS_PAGE_LIMIT, ge=1, le=MAX_USERS_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=200),
) -> AdminUsersPageOut:
    last_login_subquery = (
        select(UserSession.user_id, func.max(UserSession.created_at).label("last_login_at"))
        .group_by(UserSession.user_id)
        .subquery()
    )
    space_count_subquery = (
        select(SpaceMember.user_id, func.count().label("space_count"))
        .group_by(SpaceMember.user_id)
        .subquery()
    )
    team_count_subquery = (
        select(TeamMember.user_id, func.count().label("team_count"))
        .group_by(TeamMember.user_id)
        .subquery()
    )

    filters = []
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(or_(User.name.ilike(pattern), User.email.ilike(pattern)))

    count_query = select(func.count()).select_from(User)
    for condition in filters:
        count_query = count_query.where(condition)
    total = await db.scalar(count_query) or 0

    rows_query = (
        select(
            User,
            last_login_subquery.c.last_login_at,
            func.coalesce(space_count_subquery.c.space_count, 0),
            func.coalesce(team_count_subquery.c.team_count, 0),
        )
        .outerjoin(last_login_subquery, last_login_subquery.c.user_id == User.id)
        .outerjoin(space_count_subquery, space_count_subquery.c.user_id == User.id)
        .outerjoin(team_count_subquery, team_count_subquery.c.user_id == User.id)
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    for condition in filters:
        rows_query = rows_query.where(condition)
    rows = (await db.execute(rows_query)).all()

    items = [
        AdminUserOut(
            id=user.id,
            email=user.email,
            name=user.name,
            avatar_url=user_avatar_url(user),
            is_platform_admin=user.is_platform_admin,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=last_login_at,
            space_count=space_count,
            team_count=team_count,
        )
        for user, last_login_at, space_count, team_count in rows
    ]
    return AdminUsersPageOut(items=items, total=total, limit=limit, offset=offset)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user_admin_flag(
    user_id: UUID,
    payload: AdminUpdateUserRequest,
    _admin: AdminStepUp,
    db: DBSession,
    _: CSRF,
) -> AdminUserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if payload.is_platform_admin is not None:
        await set_platform_admin(db, user, is_admin=payload.is_platform_admin)
    if payload.is_active is not None:
        if user.id == _admin.id and not payload.is_active:
            raise HTTPException(status.HTTP_409_CONFLICT, "Admins cannot deactivate themselves")
        user.is_active = payload.is_active
        if not payload.is_active:
            user.auth_version += 1
    if payload.force_logout:
        user.auth_version += 1
    await db.commit()

    last_login_at = await db.scalar(
        select(func.max(UserSession.created_at)).where(UserSession.user_id == user.id)
    )
    space_count = (
        await db.scalar(
            select(func.count()).select_from(SpaceMember).where(SpaceMember.user_id == user.id)
        )
        or 0
    )
    team_count = (
        await db.scalar(
            select(func.count()).select_from(TeamMember).where(TeamMember.user_id == user.id)
        )
        or 0
    )

    return AdminUserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user_avatar_url(user),
        is_platform_admin=user.is_platform_admin,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=last_login_at,
        space_count=space_count,
        team_count=team_count,
    )


@router.get("/users/{user_id}/spaces")
async def list_user_spaces(
    user_id: UUID, _admin: AdminUser, db: DBSession
) -> list[dict[str, object]]:
    spaces = list(
        await db.scalars(
            select(Space)
            .join(SpaceMember, SpaceMember.space_id == Space.id)
            .where(SpaceMember.user_id == user_id)
            .options(selectinload(Space.members))
        )
    )
    return [
        {
            "id": str(space.id),
            "name": space.name,
            "members_count": len(space.members),
        }
        for space in spaces
    ]


@router.get("/funnel", response_model=AdminFunnelOut)
async def get_funnel(_admin: AdminUser, db: DBSession) -> AdminFunnelOut:
    async def count(query) -> int:
        return await db.scalar(query) or 0

    total_users = await count(select(func.count()).select_from(User))
    has_space = await count(select(func.count(func.distinct(SpaceMember.user_id))))
    has_team = await count(select(func.count(func.distinct(TeamMember.user_id))))
    has_board_or_page = await count(
        select(func.count(func.distinct(User.id)))
        .select_from(User)
        .where(
            or_(
                User.id.in_(select(IssueBoard.created_by_id)),
                User.id.in_(select(Page.created_by_id)),
            )
        )
    )
    has_task = await count(select(func.count(func.distinct(Task.created_by_id))))

    steps = [
        AdminFunnelStepOut(label="Зарегистрировались", count=total_users),
        AdminFunnelStepOut(label="Space (создали или вступили)", count=has_space),
        AdminFunnelStepOut(label="Team (создали или вступили)", count=has_team),
        AdminFunnelStepOut(label="Создали Board или Page", count=has_board_or_page),
        AdminFunnelStepOut(label="Создали Task", count=has_task),
    ]
    return AdminFunnelOut(steps=steps)


@router.get("/registrations-timeseries", response_model=AdminRegistrationsOut)
async def get_registrations_timeseries(
    _admin: AdminUser,
    db: DBSession,
    days: int = Query(30, ge=1, le=365),
) -> AdminRegistrationsOut:
    since = datetime.now(UTC) - timedelta(days=days)
    day_expr = func.date(User.created_at)
    rows = (
        await db.execute(
            select(day_expr.label("day"), func.count().label("count"))
            .where(User.created_at >= since)
            .group_by(day_expr)
            .order_by(day_expr)
        )
    ).all()
    points = [AdminRegistrationPointOut(date=str(row.day), count=row.count) for row in rows]
    return AdminRegistrationsOut(points=points)
