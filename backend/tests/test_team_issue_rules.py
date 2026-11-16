from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import CheckConstraint

from app.models import Task, Team, TeamMember
from app.schemas import TaskCreate, TaskUpdate, TeamMemberCreate
from app.services.memberships import (
    TeamActorContext,
    can_edit_page,
    ensure_can_assign_team_role,
    ensure_can_change_task_status,
    ensure_can_edit_page,
    ensure_can_manage_team_resources,
    ensure_team_owner_survives,
    get_allowed_task_update_fields,
    validate_task_update_permissions,
)


def _context(*, space_role: str, team_role: str | None) -> TeamActorContext:
    return TeamActorContext(
        team=Team(id=uuid4(), space_id=uuid4(), name="Team", created_by_id=uuid4()),
        space_membership=type("SpaceMembership", (), {"role": space_role})(),
        team_membership=(
            TeamMember(team_id=uuid4(), user_id=uuid4(), role=team_role)
            if team_role is not None
            else None
        ),
    )


def test_team_member_roles_are_restricted_in_schema_and_model() -> None:
    with pytest.raises(ValidationError):
        TeamMemberCreate(user_id=uuid4(), role="superadmin")

    checks = {
        str(constraint.sqltext)
        for constraint in TeamMember.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "role IN ('owner', 'admin', 'member')" in checks


def test_team_member_permission_matrix() -> None:
    owner = _context(space_role="member", team_role="owner")
    admin = _context(space_role="member", team_role="admin")
    member = _context(space_role="member", team_role="member")
    space_admin = _context(space_role="admin", team_role=None)

    ensure_can_assign_team_role(context=owner, new_role="owner")
    ensure_can_assign_team_role(context=admin, new_role="admin")
    ensure_can_assign_team_role(context=space_admin, new_role="member")

    with pytest.raises(HTTPException) as member_error:
        ensure_can_assign_team_role(context=member, new_role="member")
    assert member_error.value.status_code == 403

    with pytest.raises(HTTPException) as owner_error:
        ensure_can_assign_team_role(context=admin, new_role="owner")
    assert owner_error.value.status_code == 403


def test_team_resource_permission_matrix() -> None:
    owner = _context(space_role="member", team_role="owner")
    admin = _context(space_role="member", team_role="admin")
    member = _context(space_role="member", team_role="member")
    space_admin = _context(space_role="admin", team_role=None)

    for manager in (owner, admin, space_admin):
        assert manager.can_manage_resources
        ensure_can_manage_team_resources(manager)
        assert get_allowed_task_update_fields(manager) == {
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
        validate_task_update_permissions(
            manager,
            {"title", "description", "assignee_id", "deadline", "status_id"},
        )

    assert not member.can_manage_resources
    assert get_allowed_task_update_fields(member) == frozenset()
    with pytest.raises(HTTPException) as resource_error:
        ensure_can_manage_team_resources(member)
    assert resource_error.value.status_code == 403


@pytest.mark.parametrize(
    "field_name",
    ["title", "description", "assignee_id", "deadline", "status_id"],
)
def test_member_cannot_patch_any_task_field(field_name: str) -> None:
    member = _context(space_role="member", team_role="member")

    with pytest.raises(HTTPException) as exc_info:
        validate_task_update_permissions(member, {field_name})
    assert exc_info.value.status_code == 403
    assert field_name in exc_info.value.detail


def test_task_status_permission_helper_allows_managers_and_only_own_member_task() -> None:
    user_id = uuid4()
    other_user_id = uuid4()
    owner = _context(space_role="member", team_role="owner")
    admin = _context(space_role="member", team_role="admin")
    member = _context(space_role="member", team_role="member")

    ensure_can_change_task_status(owner, user_id=user_id, assignee_id=None)
    ensure_can_change_task_status(admin, user_id=user_id, assignee_id=other_user_id)
    ensure_can_change_task_status(member, user_id=user_id, assignee_id=user_id)

    for assignee_id in (None, other_user_id):
        with pytest.raises(HTTPException) as exc_info:
            ensure_can_change_task_status(
                member,
                user_id=user_id,
                assignee_id=assignee_id,
            )
        assert exc_info.value.status_code == 403


def test_page_permission_helper_is_author_or_manager() -> None:
    author_id = uuid4()
    other_user_id = uuid4()
    owner = _context(space_role="member", team_role="owner")
    admin = _context(space_role="member", team_role="admin")
    member = _context(space_role="member", team_role="member")

    assert can_edit_page(
        owner,
        user_id=other_user_id,
        created_by_id=author_id,
    )
    assert can_edit_page(
        admin,
        user_id=other_user_id,
        created_by_id=author_id,
    )
    assert can_edit_page(
        member,
        user_id=author_id,
        created_by_id=author_id,
    )
    assert not can_edit_page(
        member,
        user_id=other_user_id,
        created_by_id=author_id,
    )

    ensure_can_edit_page(
        member,
        user_id=author_id,
        created_by_id=author_id,
    )
    with pytest.raises(HTTPException) as exc_info:
        ensure_can_edit_page(
            member,
            user_id=other_user_id,
            created_by_id=author_id,
        )
    assert exc_info.value.status_code == 403


def test_last_team_owner_cannot_be_removed_or_demoted() -> None:
    for resulting_role in ("admin", "member", None):
        with pytest.raises(HTTPException) as exc_info:
            ensure_team_owner_survives(
                target_role="owner",
                resulting_role=resulting_role,
                owner_count=1,
            )
        assert exc_info.value.status_code == 409


def test_task_patch_distinguishes_omitted_assignee_from_null() -> None:
    omitted = TaskUpdate(title="Changed")
    cleared = TaskUpdate(assignee_id=None)
    assigned_id = uuid4()
    assigned = TaskUpdate(assignee_id=assigned_id)

    assert "assignee_id" not in omitted.model_fields_set
    assert "assignee_id" in cleared.model_fields_set
    assert cleared.assignee_id is None
    assert assigned.assignee_id == assigned_id


def test_new_task_defaults_to_unassigned() -> None:
    payload = TaskCreate(title="Issue")
    assert payload.assignee_id is None


def test_task_assignee_column_is_nullable_and_uses_set_null() -> None:
    column = Task.__table__.c.assignee_id
    assert column.nullable is True
    foreign_key = next(iter(column.foreign_keys))
    assert foreign_key.ondelete == "SET NULL"


def test_migration_uses_fixed_constraint_names() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0002_encrypted_content_and_space_memberships.py"
    ).read_text()
    for name in (
        "ck_tasks_title_length",
        "ck_tasks_description_length",
        "ck_pages_title_length",
        "ck_pages_markdown_length",
        "ck_space_memberships_role_valid",
    ):
        assert f'op.f("{name}")' in migration
    assert 'drop_constraint("ck_tasks_title_length"' not in migration


def test_optional_assignee_migration_uses_set_null_and_fixed_names() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0003_team_members_and_optional_assignee.py"
    ).read_text()
    assert 'op.f("fk_tasks_assignee_id_users")' in migration
    assert 'op.f("ck_team_members_role_valid")' in migration
    assert 'ondelete="SET NULL"' in migration
    assert '"assignee_id",\n        existing_type=sa.Uuid(),\n        nullable=True' in migration
