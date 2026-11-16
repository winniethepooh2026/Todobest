"""Standalone CLI for operational tasks that don't belong behind the HTTP API.

Usage (inside the backend venv, after `pip install -e ".[dev]"`):

    noki add admin@example.com      # grant platform admin
    noki remove admin@example.com   # revoke platform admin
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import func, select

from app.db.session import async_session_factory, dispose_engine
from app.models import User
from app.services.admin import set_platform_admin
from app.services.production_backfill import backfill_production_data


async def _set_admin(email: str, *, is_admin: bool) -> int:
    normalized_email = email.strip().lower()
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(func.lower(User.email) == normalized_email))
        if user is None:
            print(f"No user with email {email!r}", file=sys.stderr)
            return 1
        await set_platform_admin(db, user, is_admin=is_admin)
    verb = "Granted" if is_admin else "Revoked"
    print(f"{verb} platform admin for {user.email}")
    return 0


async def _backfill(batch_size: int) -> int:
    async with async_session_factory() as db:
        counts = await backfill_production_data(db, batch_size=batch_size)
    print(
        "Production backfill complete: "
        + ", ".join(f"{name}={count}" for name, count in counts.items())
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="noki", description="Noki operational CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Grant platform admin access")
    add_parser.add_argument("email", help="Email of the user to promote")

    remove_parser = subparsers.add_parser("remove", help="Revoke platform admin access")
    remove_parser.add_argument("email", help="Email of the user to demote")

    backfill_parser = subparsers.add_parser(
        "backfill-production-data",
        help="Resume data backfills added by online schema migrations",
    )
    backfill_parser.add_argument("--batch-size", type=int, default=250)

    args = parser.parse_args()

    async def run() -> int:
        try:
            if args.command == "backfill-production-data":
                return await _backfill(args.batch_size)
            return await _set_admin(args.email, is_admin=args.command == "add")
        finally:
            await dispose_engine()

    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
