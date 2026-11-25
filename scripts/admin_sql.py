"""Print the SQL that creates (or resets) an admin, for pasting into the
Railway Postgres «Data → Query» box. Nothing is installed and nothing touches
a database here: the password is typed in, hashed locally, and only the hash
ends up in the SQL.

    .venv/bin/python scripts/admin_sql.py boss            # role SUPER_ADMIN
    .venv/bin/python scripts/admin_sql.py dj DJ
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyfe.core.security import hash_password  # noqa: E402
from lyfe.models import AdminRole  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    login = sys.argv[1].strip()
    role = (sys.argv[2] if len(sys.argv) > 2 else AdminRole.SUPER_ADMIN).upper()
    if role not in AdminRole.ALL:
        print(f"Unknown role {role}. Use one of: {', '.join(AdminRole.ALL)}")
        raise SystemExit(1)
    if not login or "'" in login or len(login) > 64:
        print("Login: up to 64 characters, no quotes.")
        raise SystemExit(1)

    password = getpass.getpass("Придумай пароль (не меньше 8 знаков, на экране не видно): ")
    if len(password) < 8:
        print("Слишком короткий.")
        raise SystemExit(1)
    if getpass.getpass("Ещё раз: ") != password:
        print("Пароли не совпали.")
        raise SystemExit(1)

    h = hash_password(password)
    print("\nСкопируй всё ниже и вставь в Railway → Postgres → Data → Query:\n")
    print(
        "INSERT INTO admin_users (login, password_hash, role, is_active)\n"
        f"VALUES ('{login}', '{h}', '{role}', true)\n"
        "ON CONFLICT (login) DO UPDATE SET password_hash = EXCLUDED.password_hash,\n"
        "  role = EXCLUDED.role, is_active = true, updated_at = now();"
    )


if __name__ == "__main__":
    main()
