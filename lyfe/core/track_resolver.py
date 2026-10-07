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

Links: Apple Music and Deezer links carry a catalogue id and are looked up
exactly. Everything else is read as text — oEmbed (YouTube, TikTok, SoundCloud)
or the page's link preview (Spotify and the rest) — and that text is fed back
into the catalogue search, so a link and a typed name end up in the same place.
A link that yields nothing readable is reported as such, never stored as-is.

Every network call is wrapped: if a provider fails, the user still gets to add
their track by hand. The bot must never show a technical error here.
"""
import asyncio
import difflib
import html
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
        return f"{self.artist_name} - {self.title}"

    @property
    def normalized_key(self) -> str:
        return build_normalized_key(self.artist_name, self.title)


# --------------------------------------------------------------------------
# Normalisation — this is what makes deduplication work
# --------------------------------------------------------------------------

_FEAT = re.compile(r"\s*(feat\.?|ft\.?|featuring|com|вместе с)\s+.*$", re.IGNORECASE)
_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_NOISE = re.compile(
    r"\b(remaster(ed)?( \d{4})?|\d{4} remaster(ed)?|radio edit|official (music )?video|"
    r"official audio|official|lyrics?|lyric video|visuali[sz]er|audio|hd|hq|4k|explicit|"
    r"clean|single version|album version|bonus track|prod\.? by .*)\b",
    re.IGNORECASE,
)
# "Song - Remastered 2011", "Song - Radio Edit": the part after the dash is a
# version note, not the name. A plain " - " inside a title is left alone.
_VERSION_SUFFIX = re.compile(
    r"\s+[-–—]\s+[^-–—]*\b(remaster(ed)?|edit|version|mono|stereo|live|from .*)\b[^-–—]*$",
    re.IGNORECASE,
)
# Everything after the first of these in an artist field is a guest.
_ARTIST_SPLIT = re.compile(
    r"\s*(,|&|;|/|\+|\s[xх×]\s|\bfeat\.?|\bft\.?|\bfeaturing\b|\band\b|\sи\s|\svs\.?\s)\s*",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^\w]+", re.UNICODE)

# Catalogues disagree on script: iTunes says "Макс Корж", Deezer "Max Korzh".
# Keys are built in Latin so both spellings land on the same row.
_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e", "ё": "e",
    "є": "e", "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "i", "й": "i", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})
# Spelling variants that transliteration alone cannot reconcile.
_LATIN_FOLD = (("ks", "x"), ("kh", "h"), ("ck", "k"), ("ph", "f"), ("w", "v"), ("y", "i"), ("j", "i"))


def _normalize_part(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("$", "s")
    value = re.sub(r"(?<=\w)!(?=\w)", "i", value)      # FE!N -> fein
    value = _BRACKETS.sub(" ", value)
    value = _VERSION_SUFFIX.sub(" ", value)
    value = _FEAT.sub(" ", value)
    value = _NOISE.sub(" ", value)
    value = value.translate(_TRANSLIT)
    value = _NON_ALNUM.sub("", value).replace("_", "")
    for source, target in _LATIN_FOLD:
        value = value.replace(source, target)
    return value


def primary_artist(artist: str) -> str:
    """'Travis Scott, Playboi Carti' -> 'Travis Scott'.

    Catalogues list guests in the artist field inconsistently, so only the lead
    artist takes part in the key.
    """
    artist = (artist or "").strip()
    head = _ARTIST_SPLIT.split(artist, maxsplit=1)[0].strip()
    return head or artist


def build_normalized_key(artist: str, title: str) -> str:
    """'Travis Scott, Playboi Carti' + 'FE!N (feat. Playboi Carti)' -> 'travisscott|fein'."""
    return f"{_normalize_part(primary_artist(artist))}|{_normalize_part(title)}"


def similarity(a_artist: str, a_title: str, b_artist: str, b_title: str) -> float:
    """0..1, how likely two artist/title pairs are the same recording.

    Used to catch what the exact key misses: typos, "Макс Корж" vs "Max Korzh",
    a manual entry with the artist omitted.
    """
    ta, tb = _normalize_part(a_title), _normalize_part(b_title)
    if not ta or not tb:
        return 0.0
    title_score = difflib.SequenceMatcher(None, ta, tb).ratio()

    aa = _normalize_part(primary_artist(a_artist))
    ab = _normalize_part(primary_artist(b_artist))
    if not aa or not ab:
        # One side has no artist (typed by hand): the title must carry it alone.
        return title_score * 0.95 if min(len(ta), len(tb)) >= 5 else 0.0
    artist_score = difflib.SequenceMatcher(None, aa, ab).ratio()
    if aa in ab or ab in aa:
        artist_score = max(artist_score, 0.9)
    return min(title_score, artist_score) * 0.5 + title_score * 0.5


SAME_TRACK_THRESHOLD = 0.9


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
    """Turn any music link into a searchable string. Never raises.

    Most platforms expose an oEmbed endpoint that returns the title without
    authentication, so one generic path covers almost everything. Anything else
    falls back to reading the page's og:title, which is what the link preview in
    Telegram shows anyway.
    """
    host = (urlparse(url).hostname or "").lower()
    client = _get_client()

    oembed = {
        "youtube.com": "https://www.youtube.com/oembed?url={url}&format=json",
        "youtu.be": "https://www.youtube.com/oembed?url={url}&format=json",
        "music.youtube.com": "https://www.youtube.com/oembed?url={url}&format=json",
        "tiktok.com": "https://www.tiktok.com/oembed?url={url}",
        "vm.tiktok.com": "https://www.tiktok.com/oembed?url={url}",
        "soundcloud.com": "https://soundcloud.com/oembed?format=json&url={url}",
        "on.soundcloud.com": "https://soundcloud.com/oembed?format=json&url={url}",
        "mixcloud.com": "https://www.mixcloud.com/oembed/?url={url}&format=json",
    }

    endpoint = None
    for domain, template in oembed.items():
        if host == domain or host.endswith("." + domain):
            endpoint = template.format(url=quote(url, safe=""))
            break

    try:
        if endpoint:
            response = await client.get(endpoint)
            response.raise_for_status()
            data = response.json()
            title = (data.get("title") or "").strip()
            author = _clean_channel(data.get("author_name") or "")

            # TikTok titles are captions, not track names; the useful part is
            # whatever sits before the hashtags.
            if "tiktok" in host:
                title = title.split("#")[0].strip()
                return title or None

            # SoundCloud titles read "Blinding Lights by The Weeknd".
            if "soundcloud" in host:
                by = re.match(r"^(.+?)\s+by\s+(.+)$", title)
                if by:
                    return f"{by.group(2)} - {by.group(1)}"

            # "The Weeknd - Blinding Lights" already names the artist; prefixing
            # the channel ("TheWeekndVEVO") only breaks the catalogue search.
            if split_artist_title(_clean_link_title(title)):
                return title or None
            if author and _normalize_part(author) not in _normalize_part(title):
                return f"{author} - {title}".strip()
            return title or None

        if "music.apple.com" in host:
            # Usually answered by exact_from_link(); this is the fallback when the
            # lookup is down: .../album/never-gonna-give-you-up/12345?i=678
            for part in reversed([p for p in urlparse(url).path.split("/") if p]):
                if part.isdigit() or len(part) <= 2:
                    continue
                return part.replace("-", " ")
            return None

        # Anything else: read the page title the way a link preview would.
        return await _title_from_page(url)

    except Exception as exc:  # noqa: BLE001 - links are best effort by design
        logger.info("Could not read link %s: %s", url, exc)
        return None


_OG_TITLE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE
)
_MUSICIAN = re.compile(
    r'<meta[^>]+name=["\']music:musician_description["\'][^>]+content=["\']([^"\']+)',
    re.IGNORECASE,
)
_HTML_TITLE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)
# Titles a site shows when it would not tell us anything: a login wall, a
# region block, an app-download page. Reading these as a track name is exactly
# how nonsense ended up in the DJ list.
_GENERIC_TITLES = re.compile(
    r"^(vk|вконтакте|tiktok|spotify|youtube|deezer|soundcloud|apple music|"
    r"яндекс\.?\s?музыка|yandex\.?\s?music)\b.*$|web player|make your day|"
    r"собираем музыку|sign in|log in|войти|access denied|just a moment|404|not found",
    re.IGNORECASE,
)
# Link previews are served to Telegram's crawler even by sites that show a
# blank app shell to everyone else (Spotify among them).
_PREVIEW_UA = "TelegramBot (like TwitterBot)"
_SITE_SUFFIX = re.compile(
    r"\s*[|\-–—]\s*(youtube|spotify|soundcloud|tiktok|apple music|"
    r"yandex\.?music|яндекс музыка|вконтакте|vk|music)\s*$",
    re.IGNORECASE,
)


_CHANNEL_NOISE = re.compile(r"(\s*-\s*topic|vevo|\s*official|\s*music|\s*tv)$", re.IGNORECASE)


def _clean_channel(author: str) -> str:
    """'TheWeekndVEVO' -> 'TheWeekndVEVO' minus VEVO; 'Adele - Topic' -> 'Adele'."""
    author = author.strip()
    for _ in range(3):
        cleaned = _CHANNEL_NOISE.sub("", author).strip()
        if cleaned == author:
            break
        author = cleaned
    return author


async def _title_from_page(url: str) -> str | None:
    """Last resort: read the page the way Telegram's link preview does. Works
    for Spotify, Deezer, Bandcamp and most sites we have not special-cased."""
    response = await _get_client().get(
        url, headers={"Accept": "text/html", "User-Agent": _PREVIEW_UA}
    )
    response.raise_for_status()
    html_text = response.text[:300_000]

    match = _OG_TITLE.search(html_text) or _HTML_TITLE.search(html_text)
    if not match:
        return None

    title = html.unescape(match.group(1)).strip()
    title = _SITE_SUFFIX.sub("", title).strip()
    if not title or _GENERIC_TITLES.search(title):
        return None

    musician = _MUSICIAN.search(html_text)
    if musician:
        artist = html.unescape(musician.group(1)).strip()
        if artist and _normalize_part(artist) not in _normalize_part(title):
            return f"{artist} - {title}"
    return title


async def exact_from_link(url: str) -> ResolvedTrack | None:
    """Links that carry a catalogue id need no guessing at all."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    client = _get_client()
    try:
        if "music.apple.com" in host or "itunes.apple.com" in host:
            # Song links: ?i=<trackId> on an album URL, or /song/<slug>/<trackId>.
            query_id = re.search(r"[?&]i=(\d+)", url)
            path_id = re.search(r"/song/[^/]+/(\d+)", parsed.path)
            track_id = (query_id or path_id).group(1) if (query_id or path_id) else None
            if not track_id:
                return None
            response = await client.get(
                f"https://itunes.apple.com/lookup?id={track_id}&country={STOREFRONT}"
            )
            response.raise_for_status()
            for item in response.json().get("results", []):
                if item.get("kind") == "song" and item.get("artistName") and item.get("trackName"):
                    cover = item.get("artworkUrl100")
                    return ResolvedTrack(
                        artist_name=item["artistName"],
                        title=item["trackName"],
                        album_name=item.get("collectionName"),
                        cover_url=cover.replace("100x100", "600x600") if cover else None,
                        external_url=item.get("trackViewUrl"),
                        duration_ms=item.get("trackTimeMillis"),
                        provider="itunes",
                        provider_track_id=str(item.get("trackId")),
                    )
            return None

        if "deezer.com" in host:
            match = re.search(r"/track/(\d+)", parsed.path)
            if not match:
                return None
            response = await client.get(f"https://api.deezer.com/track/{match.group(1)}")
            response.raise_for_status()
            item = response.json()
            artist = (item.get("artist") or {}).get("name")
            if not artist or not item.get("title"):
                return None
            album = item.get("album") or {}
            return ResolvedTrack(
                artist_name=artist,
                title=item["title"],
                album_name=album.get("title"),
                cover_url=album.get("cover_big") or album.get("cover_medium"),
                external_url=item.get("link"),
                duration_ms=(item.get("duration") or 0) * 1000 or None,
                provider="deezer",
                provider_track_id=str(item.get("id")),
            )
    except Exception as exc:  # noqa: BLE001 - links are best effort by design
        logger.info("Exact lookup failed for %s: %s", url, exc)
    return None


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


@dataclass
class Resolution:
    """What a piece of user input turned into.

    link        the URL found in the input, if any
    link_text   what that link was read as ("Travis Scott FE!N"); None when the
                page could not be read at all
    candidates  catalogue matches, best first
    """

    candidates: list[ResolvedTrack]
    link: str | None = None
    link_text: str | None = None

    @property
    def link_unreadable(self) -> bool:
        return self.link is not None and not self.link_text


async def resolve_detailed(text: str, limit: int = MAX_RESULTS) -> Resolution:
    """Like resolve(), but says what happened to a link.

    A link that cannot be read must never end up as a track called
    "https://...". The caller uses link_unreadable to ask for another link or the
    name instead.
    """
    text = (text or "").strip()
    if not text:
        return Resolution(candidates=[])

    url = find_url(text)
    if url:
        exact = await exact_from_link(url)
        if exact is not None:
            others = await _search(f"{exact.artist_name} {exact.title}", limit)
            candidates = [exact] + [c for c in others if not _same(c, exact)]
            return Resolution(
                candidates=candidates[:limit], link=url, link_text=exact.display
            )

        extracted = await _text_from_link(url)
        if not extracted or find_url(extracted):
            return Resolution(candidates=[], link=url)
        extracted = _clean_link_title(extracted)
        candidates = await _search(extracted, limit)
        if not candidates:
            # Page titles carry extra words the catalogue does not know
            # ("Artist - Title | Live at …"); the bare title often still matches.
            parsed = split_artist_title(extracted)
            if parsed:
                candidates = await _search(f"{parsed[0]} {parsed[1]}", limit)
        return Resolution(candidates=candidates, link=url, link_text=extracted)

    return Resolution(candidates=await _search(text, limit))


async def resolve(text: str, limit: int = MAX_RESULTS) -> list[ResolvedTrack]:
    """Return catalogue candidates for whatever the user typed or pasted.

    An empty list means the user should type the track in by hand — it is a
    normal outcome, not an error.
    """
    return (await resolve_detailed(text, limit)).candidates


def _clean_link_title(text: str) -> str:
    """'Travis Scott - FE!N (Official Video) [HD]' -> 'Travis Scott - FE!N'."""
    text = _BRACKETS.sub(" ", text)
    text = re.sub(r"\b(official (music )?video|official audio|lyrics?|lyric video|"
                  r"visuali[sz]er|hd|hq|4k)\b", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip(" -–—|")


async def _search(text: str, limit: int) -> list[ResolvedTrack]:
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

    merged: list[ResolvedTrack] = []
    for (name, _), response in zip(PROVIDERS, responses):
        if isinstance(response, BaseException):
            logger.warning("Provider %s failed for %r: %s", name, text, response)
            continue
        for track in response:
            # First provider to supply a track wins, so iTunes metadata is
            # preferred. Near-identical spellings collapse here too, so the
            # list never offers the same song twice.
            if any(_same(track, kept) for kept in merged):
                continue
            merged.append(track)

    if not merged:
        return []

    ranked = sorted(merged, key=lambda tr: _relevance(text, tr), reverse=True)
    _cache[cache_key] = (time.time(), ranked)
    return ranked[:limit]


def _same(a: ResolvedTrack, b: ResolvedTrack) -> bool:
    if a.normalized_key == b.normalized_key:
        return True
    return similarity(a.artist_name, a.title, b.artist_name, b.title) >= SAME_TRACK_THRESHOLD


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
    """Build a track from raw user input when no catalogue matched.

    Callers must reject links before getting here (see find_url): a URL is not
    a track name, and storing one is how the DJ list ended up with entries
    nobody could read."""
    text = " ".join((text or "").split())
    parsed = split_artist_title(text)
    if parsed:
        artist, title = parsed
    else:
        artist, title = "", text
    return ResolvedTrack(artist_name=artist, title=title, provider="manual")
