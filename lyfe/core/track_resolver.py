"""
Track resolution: text or link -> structured track data.

Why this exists: free-text track names cannot be deduplicated. "Travis Scott —
FE!N", "travis scott fein" and "FE!N (feat. Playboi Carti)" are one song and
three strings. Pushing everyone through a catalogue means the DJ sees one line
with a counter instead of three lines that look unrelated.

Provider chain, in order:
  1. iTunes Search API  — no key, no auth, stable for over a decade
  2. Deezer public API  — fallback if iTunes is rate limited or down
  3. Manual entry       — handled by the caller, flagged needs_review

Links are resolved via public oEmbed endpoints (YouTube, Spotify) or by reading
the slug out of the URL (Apple Music). Whatever text comes out is then fed back
into the catalogue search, so a link and a typed name end up in the same place.

Every network call is wrapped: if a provider fails, the user still gets to add
their track by hand. The bot must never show a technical error here.
"""
import asyncio
import difflib
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT = 6.0
CACHE_TTL = 3600
MAX_RESULTS = 5
FETCH_PER_PROVIDER = 12
STOREFRONT = "SK"


@dataclass(frozen=True)
class ResolvedTrack:
    artist_name: str
    title: str
    album_name: str | None = None
    cover_url: str | None = None
    external_url: str | None = None
    duration_ms: int | None = None
    provider: str = "manual"
    provider_track_id: str | None = None

    @property
    def display(self) -> str:
        return f"{self.artist_name} — {self.title}"

    @property
    def normalized_key(self) -> str:
        return build_normalized_key(self.artist_name, self.title)


# --------------------------------------------------------------------------
# Normalisation — this is what makes deduplication work
# --------------------------------------------------------------------------

_FEAT = re.compile(r"\s*(feat\.?|ft\.?|featuring|com|вместе с)\s+.*$", re.IGNORECASE)
_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_NOISE = re.compile(
    r"\b(remaster(ed)?|radio edit|official (music )?video|official audio|lyrics?|"
    r"audio|hd|hq|4k|explicit|clean|single version|album version|bonus track)\b",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^\w]+", re.UNICODE)


def _normalize_part(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = _BRACKETS.sub(" ", value)
    value = _FEAT.sub(" ", value)
    value = _NOISE.sub(" ", value)
    value = _NON_ALNUM.sub("", value)
    return value


def build_normalized_key(artist: str, title: str) -> str:
    """'Travis Scott' + 'FE!N (feat. Playboi Carti)' -> 'traviscott|fein'."""
    return f"{_normalize_part(artist)}|{_normalize_part(title)}"


def split_artist_title(text: str) -> tuple[str, str] | None:
    """Parse 'Artist - Title' written with any kind of dash."""
    for sep in (" — ", " – ", " - ", " -- "):
        if sep in text:
            left, _, right = text.partition(sep)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right
    return None


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None
_cache: dict[str, tuple[float, list[ResolvedTrack]]] = {}


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=SEARCH_TIMEOUT,
            headers={"User-Agent": "LYFE/1.0 (+https://lyfeparty.example)"},
            follow_redirects=True,
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------


async def _search_itunes(query: str, limit: int) -> list[ResolvedTrack]:
    url = (
        "https://itunes.apple.com/search"
        f"?term={quote(query)}&media=music&entity=song&limit={limit}&country={STOREFRONT}"
    )
    response = await _get_client().get(url)
    response.raise_for_status()
    payload = response.json()

    tracks = []
    for item in payload.get("results", []):
        artist = item.get("artistName")
        title = item.get("trackName")
        if not artist or not title:
            continue
        cover = item.get("artworkUrl100")
        if cover:
            cover = cover.replace("100x100", "600x600")
        tracks.append(
            ResolvedTrack(
                artist_name=artist,
                title=title,
                album_name=item.get("collectionName"),
                cover_url=cover,
                external_url=item.get("trackViewUrl"),
                duration_ms=item.get("trackTimeMillis"),
                provider="itunes",
                provider_track_id=str(item.get("trackId")) if item.get("trackId") else None,
            )
        )
    return tracks


async def _search_deezer(query: str, limit: int) -> list[ResolvedTrack]:
    url = f"https://api.deezer.com/search?q={quote(query)}&limit={limit}"
    response = await _get_client().get(url)
    response.raise_for_status()
    payload = response.json()

    tracks = []
    for item in payload.get("data", []):
        artist = (item.get("artist") or {}).get("name")
        title = item.get("title")
        if not artist or not title:
            continue
        album = item.get("album") or {}
        tracks.append(
            ResolvedTrack(
                artist_name=artist,
                title=title,
                album_name=album.get("title"),
                cover_url=album.get("cover_big") or album.get("cover_medium"),
                external_url=item.get("link"),
                duration_ms=(item.get("duration") or 0) * 1000 or None,
                provider="deezer",
                provider_track_id=str(item.get("id")) if item.get("id") else None,
            )
        )
    return tracks


PROVIDERS = (("itunes", _search_itunes), ("deezer", _search_deezer))


# --------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://\S+")


def find_url(text: str) -> str | None:
    match = _URL_RE.search(text or "")
    return match.group(0) if match else None


async def _text_from_link(url: str) -> str | None:
    """Turn a music link into a searchable string. Never raises."""
    host = (urlparse(url).hostname or "").lower()
    try:
        client = _get_client()

        if "youtube.com" in host or "youtu.be" in host:
            r = await client.get(
                f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json"
            )
            r.raise_for_status()
            data = r.json()
            title = data.get("title") or ""
            author = (data.get("author_name") or "").removesuffix(" - Topic")
            return f"{author} {title}".strip() or None

        if "spotify.com" in host:
            r = await client.get(f"https://open.spotify.com/oembed?url={quote(url, safe='')}")
            r.raise_for_status()
            return (r.json().get("title") or "").strip() or None

        if "music.apple.com" in host:
            # .../album/never-gonna-give-you-up/12345?i=678  -> "never gonna give you up"
            parts = [p for p in urlparse(url).path.split("/") if p]
            for part in reversed(parts):
                if part.isdigit() or len(part) <= 2:
                    continue
                return part.replace("-", " ")
            return None
    except Exception as exc:  # noqa: BLE001 - links are best effort by design
        logger.info("Could not read link %s: %s", url, exc)
    return None


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


async def resolve(text: str, limit: int = MAX_RESULTS) -> list[ResolvedTrack]:
    """Return catalogue candidates for whatever the user typed or pasted.

    An empty list means the user should type the track in by hand — it is a
    normal outcome, not an error.
    """
    text = (text or "").strip()
    if not text:
        return []

    url = find_url(text)
    if url:
        extracted = await _text_from_link(url)
        if not extracted:
            return []
        text = extracted

    cache_key = text.lower()
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1][:limit]

    # Query every provider at once and merge. One catalogue alone is not
    # enough: iTunes tokenises "FE!N" as "fe" + "n", so searching "fein" never
    # matches it there, while Deezer copes with the same query fine.
    responses = await asyncio.gather(
        *(provider(text, FETCH_PER_PROVIDER) for _, provider in PROVIDERS),
        return_exceptions=True,
    )

    merged: dict[str, ResolvedTrack] = {}
    for (name, _), response in zip(PROVIDERS, responses):
        if isinstance(response, BaseException):
            logger.warning("Provider %s failed for %r: %s", name, text, response)
            continue
        for track in response:
            # First provider to supply a key wins, so iTunes metadata is preferred.
            merged.setdefault(track.normalized_key, track)

    if not merged:
        return []

    ranked = sorted(merged.values(), key=lambda tr: _relevance(text, tr), reverse=True)
    _cache[cache_key] = (time.time(), ranked)
    return ranked[:limit]


def _relevance(query: str, track: ResolvedTrack) -> float:
    """How well a candidate matches what the user typed.

    Providers rank by their own popularity metrics, which is why a search for
    "travis scott fein" can come back with five unrelated Travis Scott songs.
    Re-ranking on textual similarity puts the intended track first.
    """
    q = _normalize_part(query)
    if not q:
        return 0.0

    candidate = _normalize_part(track.artist_name) + _normalize_part(track.title)
    score = difflib.SequenceMatcher(None, q, candidate).ratio()

    # Reward candidates whose title actually appears in the query, which is the
    # usual shape of "artist + title" input.
    title = _normalize_part(track.title)
    if title and title in q:
        score += 0.35
    artist = _normalize_part(track.artist_name)
    if artist and artist in q:
        score += 0.15

    return score


def manual_track(text: str) -> ResolvedTrack:
    """Build a track from raw user input when no catalogue matched."""
    text = " ".join((text or "").split())
    parsed = split_artist_title(text)
    if parsed:
        artist, title = parsed
    else:
        artist, title = "", text
    return ResolvedTrack(artist_name=artist, title=title, provider="manual")
