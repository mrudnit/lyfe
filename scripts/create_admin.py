"""Create or update an admin account for the DJ live screen.

    PYTHONPATH=. .venv/bin/python scripts/create_admin.py dj "пароль" DJ

Roles: SUPER_ADMIN, ADMIN, DJ, MODERATOR, PHOTOGRAPHER.
Give the person at the booth the DJ role, not SUPER_ADMIN.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from lyfe.core.security import hash_password  # noqa: E402
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.models import AdminRole, AdminUser  # noqa: E402


async def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)

    login, password = sys.argv[1], sys.argv[2]
    role = (sys.argv[3] if len(sys.argv) > 3 else AdminRole.DJ).upper()
    if role not in AdminRole.ALL:
        print(f"Unknown role {role}. Use one of: {', '.join(AdminRole.ALL)}")
        raise SystemExit(1)
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        raise SystemExit(1)

    async with SessionFactory() as session:
        admin = await session.scalar(select(AdminUser).where(AdminUser.login == login))
        if admin is None:
            admin = AdminUser(login=login, password_hash=hash_password(password), role=role)
            session.add(admin)
            action = "Created"
        else:
            admin.password_hash = hash_password(password)
            admin.role = role
            admin.is_active = True
            action = "Updated"
        await session.commit()

    print(f"{action} admin {login!r} with role {role}")


if __name__ == "__main__":
    asyncio.run(main())
