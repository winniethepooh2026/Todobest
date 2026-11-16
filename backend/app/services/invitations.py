from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invitation, SpaceMember, TeamMember, User


async def accept_invitation_record(db: AsyncSession, invitation: Invitation, user: User) -> None:
    now = datetime.now(UTC)
    if (
        invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= now
        or (invitation.email is not None and invitation.email != user.email)
    ):
        return
    is_new_space_member = await db.get(SpaceMember, (invitation.space_id, user.id)) is None
    if is_new_space_member:
        db.add(
            SpaceMember(
                space_id=invitation.space_id,
                user_id=user.id,
                role=invitation.role,
            )
        )
    if (
        invitation.team_id is not None
        and await db.get(TeamMember, (invitation.team_id, user.id)) is None
    ):
        db.add(
            TeamMember(
                team_id=invitation.team_id,
                user_id=user.id,
                role=invitation.role,
            )
        )
    invitation.accepted_at = now


async def accept_matching_invitations(db: AsyncSession, user: User) -> int:
    email = getattr(user, "email", None)
    if not isinstance(email, str):
        return 0
    now = datetime.now(UTC)
    invitations = list(
        await db.scalars(
            select(Invitation)
            .where(
                Invitation.email == email,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > now,
            )
            .with_for_update()
        )
    )
    for invitation in invitations:
        await accept_invitation_record(db, invitation, user)
    return len(invitations)
