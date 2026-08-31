"""LYFE ID generation.

Sequential, zero-padded to four digits: 0001, 0842, 10231.
It is a public brand identifier, deliberately guessable, and must never be
used as an authentication token anywhere in the system.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SEQUENCE_NAME = "lyfe_id_seq"


async def next_lyfe_id(session: AsyncSession) -> str:
    result = await session.execute(text(f"SELECT nextval('{SEQUENCE_NAME}')"))
    value = result.scalar_one()
    return f"{value:04d}"
