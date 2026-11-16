from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import defer, selectinload

from app.api.deps import CSRF, CurrentUser, DBSession
from app.models import Page, Upload
from app.schemas import (
    Message,
    PageCreate,
    PageOut,
    PageSummary,
    PageUpdate,
    UserSummary,
)
from app.services.access import get_page_for_user, get_team_for_user
from app.services.avatars import user_avatar_url
from app.services.content_encryption import (
    get_page_content,
    get_page_markdown,
    get_page_title,
    set_page_content,
    set_page_title,
)
from app.services.images import (
    InvalidImageError,
    extract_image_filenames,
    open_image_for_read,
)
from app.services.memberships import (
    can_edit_page,
    ensure_can_edit_page,
    get_team_actor_context,
)

router = APIRouter(tags=["Pages"])


def _same_page_version(actual: datetime, expected: datetime) -> bool:
    if actual.tzinfo is None:
        actual = actual.replace(tzinfo=UTC)
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=UTC)
    return actual.astimezone(UTC) == expected.astimezone(UTC)


def _ensure_images_are_readable(filenames: set[str]) -> None:
    for filename in filenames:
        opened = open_image_for_read(filename)
        opened.stream.close()


def page_to_schema(page: Page, *, editable: bool) -> PageOut:
    return PageOut(
        id=page.id,
        team_id=page.team_id,
        title=get_page_title(page),
        content=get_page_content(page),
        markdown=get_page_markdown(page),
        created_by=UserSummary(
            id=page.created_by.id,
            name=page.created_by.name,
            email=page.created_by.email,
            avatar_url=user_avatar_url(page.created_by),
        ),
        can_edit=editable,
        can_delete=editable,
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


def page_to_summary(page: Page) -> PageSummary:
    return PageSummary(
        id=page.id,
        team_id=page.team_id,
        title=get_page_title(page),
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


@router.get("/teams/{team_id}/pages", response_model=list[PageSummary])
async def list_pages(
    team_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> list[PageSummary]:
    await get_team_for_user(db, team_id, current_user.id)
    pages = list(
        await db.scalars(
            select(Page)
            .where(Page.team_id == team_id, Page.deleted_at.is_(None))
            .options(
                defer(Page.content_ciphertext),
                defer(Page.content_nonce),
                defer(Page.content_tag),
                defer(Page.markdown_ciphertext),
                defer(Page.markdown_nonce),
                defer(Page.markdown_tag),
            )
            .order_by(Page.created_at)
        )
    )
    return [page_to_summary(page) for page in pages]


@router.post(
    "/teams/{team_id}/pages",
    response_model=PageOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_page(
    team_id: UUID,
    payload: PageCreate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> PageOut:
    await get_team_actor_context(
        db,
        team_id=team_id,
        user_id=current_user.id,
        for_update=True,
    )
    page = Page(
        id=uuid4(),
        team_id=team_id,
        created_by=current_user,
    )
    set_page_title(page, payload.title)
    set_page_content(
        page,
        {"type": "doc", "content": [{"type": "paragraph"}]},
        "",
    )
    db.add(page)
    await db.commit()
    return page_to_schema(page, editable=True)


@router.get("/pages/{page_id}", response_model=PageOut)
async def get_page(
    page_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> PageOut:
    page = await get_page_for_user(db, page_id, current_user.id)
    context = await get_team_actor_context(
        db,
        team_id=page.team_id,
        user_id=current_user.id,
    )
    editable = can_edit_page(
        context,
        user_id=current_user.id,
        created_by_id=page.created_by_id,
    )
    return page_to_schema(page, editable=editable)


@router.patch("/pages/{page_id}", response_model=PageOut)
async def update_page(
    page_id: UUID,
    payload: PageUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> PageOut:
    page = await get_page_for_user(db, page_id, current_user.id)
    context = await get_team_actor_context(
        db,
        team_id=page.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    page = await db.scalar(
        select(Page)
        .where(Page.id == page_id)
        .options(selectinload(Page.created_by))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    ensure_can_edit_page(
        context,
        user_id=current_user.id,
        created_by_id=page.created_by_id,
    )
    if not _same_page_version(page.updated_at, payload.expected_updated_at):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Page was changed elsewhere; reload before saving",
        )
    fields = payload.model_fields_set

    content_changed = "content" in fields
    markdown_changed = "markdown" in fields
    if content_changed != markdown_changed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Content and markdown must be saved together",
        )
    content = payload.content
    markdown = payload.markdown
    if content_changed and (content is None or markdown is None):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Content and markdown cannot be null",
        )

    uploads: list[Upload] = []
    filenames: set[str] = set()
    if content_changed:
        if content is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Content cannot be null",
            )
        filenames = extract_image_filenames(content)
        upload_conditions = [Upload.page_id == page.id]
        if filenames:
            upload_conditions.append(
                and_(
                    Upload.filename.in_(filenames),
                    Upload.owner_id == current_user.id,
                    Upload.page_id.is_(None),
                )
            )
        uploads = list(
            await db.scalars(
                select(Upload).where(or_(*upload_conditions)).order_by(Upload.id).with_for_update()
            )
        )
        uploads_by_filename = {upload.filename: upload for upload in uploads}
        for filename in filenames:
            upload = uploads_by_filename.get(filename)
            if upload is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Page contains an unavailable image",
                )
        try:
            await asyncio.to_thread(_ensure_images_are_readable, filenames)
        except (InvalidImageError, OSError) as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Page contains an unavailable image",
            ) from exc

    if "title" in fields:
        if payload.title is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Page title cannot be null",
            )
        set_page_title(page, payload.title)

    if content_changed:
        if content is None or markdown is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Content and markdown cannot be null",
            )
        for upload in uploads:
            if upload.filename in filenames:
                upload.page_id = page.id
                upload.space_id = context.team.space_id
            elif upload.page_id == page.id:
                upload.page_id = None

        set_page_content(page, content, markdown)

    await db.commit()
    return page_to_schema(page, editable=True)


@router.delete("/pages/{page_id}", response_model=Message)
async def delete_page(
    page_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    page = await get_page_for_user(db, page_id, current_user.id)
    context = await get_team_actor_context(
        db,
        team_id=page.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    page = await db.scalar(
        select(Page)
        .where(Page.id == page_id)
        .options(selectinload(Page.created_by))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    ensure_can_edit_page(
        context,
        user_id=current_user.id,
        created_by_id=page.created_by_id,
    )
    page.deleted_at = datetime.now(UTC)
    await db.commit()
    return Message(message="Page deleted")
