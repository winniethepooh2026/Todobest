from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Space, SpaceMember, Team, TeamMember, User
from app.services.access import get_team_for_user
from app.services.memberships import (
    can_manage_space_members,
    ensure_can_assign_role,
    ensure_can_manage_members,
    ensure_owner_survives,
)


def test_only_owner_and_admin_manage_members() -> None:
    assert can_manage_space_members("owner")
    assert can_manage_space_members("admin")
    assert not can_manage_space_members("member")

    with pytest.raises(HTTPException) as exc_info:
        ensure_can_manage_members("member")
    assert exc_info.value.status_code == 403


def test_admin_cannot_grant_or_change_owner_role() -> None:
    with pytest.raises(HTTPException) as grant_error:
        ensure_can_assign_role(actor_role="admin", new_role="owner")
    assert grant_error.value.status_code == 403

    with pytest.raises(HTTPException) as change_error:
        ensure_can_assign_role(
            actor_role="admin",
            target_role="owner",
            new_role="member",
        )
    assert change_error.value.status_code == 403


@pytest.mark.parametrize("resulting_role", ["admin", "member", None])
def test_last_owner_cannot_be_demoted_or_removed(
    resulting_role: str | None,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        ensure_owner_survives(
            target_role="owner",
            resulting_role=resulting_role,
            owner_count=1,
        )
    assert exc_info.value.status_code == 409


def test_owner_can_be_changed_when_another_owner_remains() -> None:
    ensure_owner_survives(
        target_role="owner",
        resulting_role="admin",
        owner_count=2,
    )


async def test_space_membership_is_required_before_team_access() -> None:
    pytest.importorskip("aiosqlite")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def register_sqlite_functions(dbapi_connection, connection_record) -> None:
        dbapi_connection.create_function("char_length", 1, len)

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: User.metadata.create_all(
                sync_connection,
                tables=[
                    User.__table__,
                    Space.__table__,
                    SpaceMember.__table__,
                    Team.__table__,
                    TeamMember.__table__,
                ],
            )
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid4()
    admin_id = uuid4()
    member_id = uuid4()
    outsider_id = uuid4()
    space_id = uuid4()
    team_id = uuid4()

    async with session_factory() as db:
        db.add_all(
            [
                User(id=owner_id, email="owner@example.com", name="Owner"),
                User(id=admin_id, email="admin@example.com", name="Admin"),
                User(id=member_id, email="member@example.com", name="Member"),
                User(id=outsider_id, email="outsider@example.com", name="Outsider"),
                Space(id=space_id, name="Noki", created_by_id=owner_id),
                SpaceMember(space_id=space_id, user_id=owner_id, role="owner"),
                SpaceMember(space_id=space_id, user_id=admin_id, role="admin"),
                SpaceMember(space_id=space_id, user_id=member_id, role="member"),
                Team(
                    id=team_id,
                    space_id=space_id,
                    name="Development",
                    created_by_id=owner_id,
                ),
                TeamMember(team_id=team_id, user_id=outsider_id, role="member"),
            ]
        )
        await db.commit()

        assert (await get_team_for_user(db, team_id, owner_id)).id == team_id
        assert (await get_team_for_user(db, team_id, admin_id)).id == team_id

        with pytest.raises(HTTPException) as member_error:
            await get_team_for_user(db, team_id, member_id)
        assert member_error.value.status_code == 404

        with pytest.raises(HTTPException) as outsider_error:
            await get_team_for_user(db, team_id, outsider_id)
        assert outsider_error.value.status_code == 404

        db.add(TeamMember(team_id=team_id, user_id=member_id, role="member"))
        await db.commit()
        assert (await get_team_for_user(db, team_id, member_id)).id == team_id

    await engine.dispose()
