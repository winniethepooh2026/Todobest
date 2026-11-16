from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import (
    CSRF,
    CurrentUser,
    DBSession,
    RedisClient,
    enforce_mail_recipient_rate_limit,
    enforce_rate_limit,
)
from app.core.config import settings
from app.models import Invitation, Space, Team
from app.schemas import Message
from app.schemas.invitations import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationOut,
)
from app.services.invitations import accept_invitation_record
from app.services.mail import enqueue_mail
from app.services.memberships import ensure_can_assign_role, get_space_membership
from app.services.one_time_tokens import hash_token

router = APIRouter(tags=["Invitations"])


def _out(invitation: Invitation) -> InvitationOut:
    return InvitationOut.model_validate(invitation, from_attributes=True)


@router.get("/spaces/{space_id}/invitations", response_model=list[InvitationOut])
async def list_invitations(
    space_id: UUID, current_user: CurrentUser, db: DBSession
) -> list[InvitationOut]:
    actor = await get_space_membership(db, space_id=space_id, user_id=current_user.id)
    if actor.role not in {"owner", "admin"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient Space permissions")
    rows = await db.scalars(
        select(Invitation)
        .where(Invitation.space_id == space_id)
        .order_by(Invitation.created_at.desc())
    )
    return [_out(row) for row in rows]


@router.post(
    "/spaces/{space_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    space_id: UUID,
    payload: InvitationCreate,
    current_user: CurrentUser,
    db: DBSession,
    redis: RedisClient,
    _: CSRF,
) -> InvitationCreated:
    space = await db.scalar(
        select(Space).where(Space.id == space_id, Space.deleted_at.is_(None)).with_for_update()
    )
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    actor = await get_space_membership(db, space_id=space_id, user_id=current_user.id)
    ensure_can_assign_role(actor_role=actor.role, new_role=payload.role)
    await enforce_rate_limit(
        redis,
        scope="invitation-mail-actor",
        identifier=str(current_user.id),
        limit=settings.invitation_mail_actor_rate_limit_attempts,
        window_seconds=settings.mail_rate_limit_window_seconds,
    )
    if payload.email is not None:
        await enforce_mail_recipient_rate_limit(
            redis,
            recipient=payload.email,
            purpose="invitation",
        )
    team = None
    if payload.team_id is not None:
        team = await db.scalar(
            select(Team).where(
                Team.id == payload.team_id,
                Team.space_id == space_id,
                Team.deleted_at.is_(None),
            )
        )
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    if payload.email is not None:
        duplicate = await db.scalar(
            select(Invitation.id).where(
                Invitation.space_id == space_id,
                Invitation.team_id == payload.team_id,
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
        team_id=payload.team_id,
        email=payload.email,
        token_hash=hash_token(raw_token),
        role=payload.role,
        invited_by_id=current_user.id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.invitation_ttl_days),
    )
    db.add(invitation)
    await db.commit()
    url = f"{settings.frontend_url}/invite?token={raw_token}"
    if payload.email is not None:
        enqueue_mail(
            recipient=payload.email,
            kind="invitation",
            context={
                "name": "",
                "target_name": team.name if team else space.name,
                "action_url": url,
            },
            idempotency_key=f"invitation/{invitation.id}",
        )
    return InvitationCreated(**_out(invitation).model_dump(), invitation_url=url)


@router.post("/invitations/accept", response_model=Message)
async def accept_invitation(
    payload: InvitationAccept,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    invitation = await db.scalar(
        select(Invitation)
        .where(Invitation.token_hash == hash_token(payload.token))
        .with_for_update()
    )
    if invitation is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invitation is invalid or expired")
    before = invitation.accepted_at
    await accept_invitation_record(db, invitation, current_user)
    if before is not None or invitation.accepted_at is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invitation is invalid or expired")
    await db.commit()
    return Message(message="Invitation accepted")


@router.delete("/invitations/{invitation_id}", response_model=Message)
async def revoke_invitation(
    invitation_id: UUID, current_user: CurrentUser, db: DBSession, _: CSRF
) -> Message:
    invitation = await db.scalar(
        select(Invitation).where(Invitation.id == invitation_id).with_for_update()
    )
    if invitation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    actor = await get_space_membership(db, space_id=invitation.space_id, user_id=current_user.id)
    if actor.role not in {"owner", "admin"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient Space permissions")
    invitation.revoked_at = datetime.now(UTC)
    await db.commit()
    return Message(message="Invitation revoked")
