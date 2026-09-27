#!/usr/bin/env python3
"""Write a 24-hour panel session for the reserved lab phone.

This is a hub CLI, not an HTTP route. It refuses every other number and
never prints the token.
"""

from __future__ import annotations

import asyncio
import os
import sys

from app.database import SessionLocal
from app.lab_account import require_lab_phone
from app.repositories.user_repository import UserRepository
from app.security import encode_token


async def _mint(phone: str) -> str:
    async with SessionLocal() as session:
        users = UserRepository(session)
        user = await users.get_by_phone(phone)
        if user is None:
            user = await users.create(phone, role="admin")
        return encode_token(user.id, user.role, ttl_minutes=24 * 60)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: lab_session.py PHONE OUTFILE")
    phone = require_lab_phone(sys.argv[1])
    token = asyncio.run(_mint(phone))
    outfile = sys.argv[2]
    fd = os.open(outfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    print("LAB_OK")


if __name__ == "__main__":
    main()
