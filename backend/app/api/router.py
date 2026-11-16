from fastapi import APIRouter

from app.api.routes import (
    admin,
    api_tokens,
    auth,
    avatars,
    exports,
    invitations,
    issues,
    lifecycle,
    pages,
    search,
    todos,
    uploads,
    users,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(admin.router)
api_router.include_router(api_tokens.router)
api_router.include_router(auth.router)
api_router.include_router(avatars.router)
api_router.include_router(exports.router)
api_router.include_router(users.router)
api_router.include_router(workspaces.router)
api_router.include_router(issues.router)
api_router.include_router(invitations.router)
api_router.include_router(lifecycle.router)
api_router.include_router(pages.router)
api_router.include_router(search.router)
api_router.include_router(todos.router)
api_router.include_router(uploads.router)
