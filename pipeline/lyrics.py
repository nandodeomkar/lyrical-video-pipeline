"""Stage 4 — multi-source synced-lyrics lookup + LRC parsing (FR-005).

Lookup order (mitigates R-006 — wrong-song matches from free-text search):
1. LRCLIB structured search (track_name + artist_name), ranked by duration
   proximity when the track length is known.
2. `syncedlyrics` free-text aggregator (LRCLIB + NetEase/Musixmatch/Megalobiz).
Both steps retry with parenthetical qualifiers stripped from the title:
"Right Now (Na Na Na)" matches the wrong song as free text, "Right Now" hits.
The search uses the user-confirmed metadata (FR-015).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests
import syncedlyrics

log = logging.getLogger(__name__)

LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
_LRCLIB_TIMEOUT_S = 10
# LRCLIB asks clients to identify themselves (lrclib.net/docs).
_LRCLIB_HEADERS = {"User-Agent": "LyricalVideoPipeline/1.0 (local single-user app)"}

# (...) or [...] qualifier groups inside a title.
_BRACKET_GROUP = re.compile(r"[(\[][^)\]]*[)\]]")


@dataclass
class LyricLine:
    start: float  # seconds
    text: str


def _title_variants(title: str) -> list[str]:
    """The title as confirmed, then without (...)/[...] qualifiers.

    Hooks like "(Na Na Na)" are part of the real title — the full form is
    tried first — but they derail free-text provider matching; the stripped
    form rescues those lookups (R-006).
    """
    variants = [title]
    stripped = re.sub(r"\s+", " ", _BRACKET_GROUP.sub(" ", title)).strip(" -–—")
    if stripped and stripped.lower() != title.lower():
        variants.append(stripped)
    return variants


def _lrclib_candidates(title: str, artist: str, duration: float, field: str) -> list[str]:
    """Structured LRCLIB search; returns the requested lyrics field, ranked.

    Candidates without the field (instrumental or plain-only entries) are
    skipped. With a known duration, closest-length candidates rank first, so
    album/extended/video timing variants resolve to the right one.
    """
    try:
        resp = requests.get(
            LRCLIB_SEARCH_URL,
            params={"track_name": title, "artist_name": artist},
            headers=_LRCLIB_HEADERS,
            timeout=_LRCLIB_TIMEOUT_S,
        )
        resp.raise_for_status()
        candidates = resp.json()
    except Exception:
        log.exception("LRCLIB search failed for %r / %r", title, artist)
        return []
    if not isinstance(candidates, list):
        return []
    usable = [c for c in candidates if isinstance(c, dict) and (c.get(field) or "").strip()]
    if duration > 0:
        usable.sort(key=lambda c: abs(float(c.get("duration") or 0.0) - duration))
    return [c[field] for c in usable]


def _lrclib_search(title: str, artist: str, duration: float, field: str) -> str | None:
    cands = _lrclib_candidates(title, artist, duration, field)
    return cands[0] if cands else None


def _lookup(title: str, artist: str, duration: float, field: str, synced: bool) -> str | None:
    title, artist = title.strip(), artist.strip()
    if not (title or artist):
        return None
    variants = _title_variants(title)
    for variant in variants:
        text = _lrclib_search(variant, artist, duration, field)
        if text:
            return text
    for variant in variants:
        query = f"{variant} {artist}".strip()
        try:
            # Individual providers can fail on network/format hiccups; treat
            # as a miss so the user can retry — never crash the run over a
            # lookup.
            text = syncedlyrics.search(query, **{"synced_only" if synced else "plain_only": True})
        except Exception:
            log.exception("lyrics search failed for %r", query)
            continue
        if text:
            return text
    return None


def search_synced(title: str, artist: str, duration: float = 0.0) -> str | None:
    """Return raw LRC text, or None on a miss (caller offers re-search, FR-005)."""
    return _lookup(title, artist, duration, "syncedLyrics", synced=True)


def search_synced_candidates(
    title: str, artist: str, duration: float = 0.0, limit: int = 5
) -> list[str]:
    """Up to `limit` distinct synced candidates, best-ranked first.

    For callers that can *test* a candidate against the audio (the
    transcription corrector): duration ranking alone can pick an entry whose
    timeline doesn't match this rip, so alignment needs alternatives to try.
    """
    title, artist = title.strip(), artist.strip()
    if not (title or artist):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for variant in _title_variants(title):
        for lrc in _lrclib_candidates(variant, artist, duration, "syncedLyrics"):
            if lrc not in seen:
                seen.add(lrc)
                out.append(lrc)
        if len(out) >= limit:
            return out[:limit]
    for variant in _title_variants(title):
        query = f"{variant} {artist}".strip()
        try:
            lrc = syncedlyrics.search(query, synced_only=True)
        except Exception:
            log.exception("lyrics search failed for %r", query)
            continue
        if lrc and lrc not in seen:
            seen.add(lrc)
            out.append(lrc)
            break
    return out[:limit]


def search_plain(title: str, artist: str, duration: float = 0.0) -> str | None:
    """Published plain-text lyrics (no timing) — reference text for correcting
    machine transcriptions. Plain lyrics exist for far more songs than synced
    ones, which is exactly the gap the transcription path covers."""
    return _lookup(title, artist, duration, "plainLyrics", synced=False)


# Leading timestamp tag(s): [mm:ss], [mm:ss.xx], [mm:ss.xxx], [mm:ss:xx]
_TS = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
# Enhanced-LRC word-level tags embedded in the text: <mm:ss.xx>
_WORD_TS = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>")


def parse_lrc(lrc_text: str) -> list[LyricLine]:
    """Parse LRC into sorted line-level (start, text) pairs.

    Metadata tags like [ar:...]/[ti:...] don't match the numeric timestamp
    pattern and are skipped. A line may carry several timestamps (repeated
    chorus); it yields one entry per timestamp. Empty-text lines (gap markers)
    are dropped.
    """
    entries: list[LyricLine] = []
    for raw in lrc_text.splitlines():
        raw = raw.strip()
        pos = 0
        stamps: list[float] = []
        while m := _TS.match(raw, pos):
            mins, secs, frac = m.group(1), m.group(2), m.group(3)
            t = int(mins) * 60 + int(secs)
            if frac:
                t += int(frac) / 10 ** len(frac)
            stamps.append(t)
            pos = m.end()
        if not stamps:
            continue
        text = _WORD_TS.sub("", raw[pos:]).strip()
        if not text:
            continue
        entries.extend(LyricLine(start=t, text=text) for t in stamps)
    entries.sort(key=lambda e: e.start)
    return entries
