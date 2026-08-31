"""Check the track resolver without touching Telegram or the database.

    PYTHONPATH=. .venv/bin/python scripts/check_resolver.py "travis scott fein"
    PYTHONPATH=. .venv/bin/python scripts/check_resolver.py "https://youtu.be/..."

If this prints tracks, the catalogue works. If it prints nothing, the bot will
fall back to manual entry — which is a normal outcome, not a crash.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyfe.core import track_resolver  # noqa: E402


async def main() -> None:
    query = " ".join(sys.argv[1:]) or "travis scott fein"
    print(f"Query: {query!r}\n")
    results = await track_resolver.resolve(query)
    if not results:
        print("No results — the bot would offer manual entry here.")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r.display}")
        print(f"   provider : {r.provider}")
        print(f"   album    : {r.album_name}")
        print(f"   key      : {r.normalized_key}")
        print(f"   cover    : {r.cover_url}")
    await track_resolver.close()


if __name__ == "__main__":
    asyncio.run(main())
