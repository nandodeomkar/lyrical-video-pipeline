"""Post-transcription auto-correction against online lyrics (R-004, NFR-010).

The slow path's timings are accurate but sung words get misheard where vocals
are layered. Online lyrics have the opposite property: right words, timing
that may not match this exact audio (album cut vs. music-video rip). This
module combines the two, strongest option first:

1. ``synced_aligned`` — a synced (LRC) source whose lines match the
   transcription with a near-constant per-line time offset. Adopt the online
   text and timing, shifted onto this audio's timeline. The constant offset
   doubles as match validation: a wrong song barely pairs up, and a different
   cut of the right song produces a *drifting* offset and is rejected.
2. ``plain_corrected`` — no aligned synced source; keep the transcription's
   structure and timing, replace the text of lines that closely match an
   online lyric line. Applied only when enough of the transcription matches
   the reference (a wrong-song reference must degrade to "no correction").
3. ``none`` — nothing validated; the transcription is returned unchanged.
   A lookup problem must never lose the transcription (FR-011 spirit).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from statistics import median

from .lyrics import LyricLine, parse_lrc, search_plain, search_synced_candidates

log = logging.getLogger(__name__)

_MIN_REF_LINES = 5        # fewer timed lines than this is not a usable source
_ANCHOR_MIN_TOKENS = 3    # offset anchors must be real phrases, not fragments
_ANCHOR_RATIO = 0.65      # mutual-best similarity to count as an anchor pair
_MIN_ANCHORS = 6          # pairs needed before trusting a median offset
_MAX_OFFSET_MAD_S = 1.5   # offset spread above this means a different cut
_REPLACE_RATIO = 0.60     # per-line similarity needed to adopt reference text
_VALIDATE_FRACTION = 0.6  # share of phrase lines that must match the reference
_MAX_TOKEN_DELTA = 2      # word fixes barely change length; more means the
                          # reference line spans words held by adjacent lines

# "[Chorus]" / "(Verse 2)"-style section markers in plain lyric text.
_SECTION_MARKER = re.compile(r"^\s*[\[(][^\])]*[\])]\s*$")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


@dataclass
class Correction:
    lines: list[LyricLine]
    method: str               # "synced_aligned" | "plain_corrected" | "none"
    offset: float = 0.0       # seconds added to reference times (synced_aligned)
    anchors: int = 0          # matched line pairs backing the decision
    replaced: int = 0         # lines whose text changed (plain_corrected)


def _norm(text: str) -> str:
    return _NON_ALNUM.sub("", text.lower().replace("'", "")).strip()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _mutual_anchors(
    trans: list[tuple[int, str]], ref: list[tuple[int, str]]
) -> list[tuple[int, int, float]]:
    """Pairs where each line is the other's best match at >= _ANCHOR_RATIO.

    Mutual-best filtering keeps repeated chorus lines from producing
    many-to-one pairings that would skew the offset estimate.
    """
    best_for_t: dict[int, tuple[int, float]] = {}
    best_for_r: dict[int, tuple[int, float]] = {}
    for ti, ttext in trans:
        for ri, rtext in ref:
            r = _ratio(ttext, rtext)
            if r >= _ANCHOR_RATIO:
                if r > best_for_t.get(ti, (-1, 0.0))[1]:
                    best_for_t[ti] = (ri, r)
                if r > best_for_r.get(ri, (-1, 0.0))[1]:
                    best_for_r[ri] = (ti, r)
    return [
        (ti, ri, r)
        for ti, (ri, r) in best_for_t.items()
        if best_for_r.get(ri, (-1, 0.0))[0] == ti
    ]


def _phrase_lines(lines: list[LyricLine]) -> list[tuple[int, str]]:
    out = []
    for i, ln in enumerate(lines):
        norm = _norm(ln.text)
        if len(norm.split()) >= _ANCHOR_MIN_TOKENS:
            out.append((i, norm))
    return out


def _aligned_from_synced(
    trans_lines: list[LyricLine], ref_lines: list[LyricLine], duration: float
) -> tuple[list[LyricLine], float, int] | None:
    """Adopt the reference wholesale, shifted by the median anchor offset."""
    anchors = _mutual_anchors(_phrase_lines(trans_lines), _phrase_lines(ref_lines))
    if len(anchors) < _MIN_ANCHORS:
        return None
    deltas = [trans_lines[ti].start - ref_lines[ri].start for ti, ri, _ in anchors]
    offset = median(deltas)
    spread = median(abs(d - offset) for d in deltas)
    if spread > _MAX_OFFSET_MAD_S:
        return None
    shifted = [
        LyricLine(start=ln.start + offset, text=ln.text)
        for ln in ref_lines
        if ln.start + offset >= 0 and (duration <= 0 or ln.start + offset < duration)
    ]
    if len(shifted) < _MIN_REF_LINES:
        return None
    return shifted, offset, len(anchors)


def _corrected_from_plain(
    trans_lines: list[LyricLine], ref_texts: list[str]
) -> tuple[list[LyricLine], int, int] | None:
    """Keep transcription timing; swap in reference text for close matches."""
    refs = [
        (raw.strip(), _norm(raw))
        for raw in ref_texts
        if raw.strip() and not _SECTION_MARKER.match(raw) and _norm(raw)
    ]
    if not refs:
        return None

    def best(norm_text: str) -> tuple[str, float]:
        return max(((orig, _ratio(norm_text, n)) for orig, n in refs), key=lambda p: p[1])

    phrases = _phrase_lines(trans_lines)
    if not phrases:
        return None
    matches = {i: best(norm) for i, norm in phrases}
    matched = [i for i, (_, r) in matches.items() if r >= _REPLACE_RATIO]
    if len(matched) < _MIN_ANCHORS or len(matched) / len(phrases) < _VALIDATE_FRACTION:
        return None

    replaced = 0
    new_lines: list[LyricLine] = []
    for i, ln in enumerate(trans_lines):
        pick = matches.get(i)
        if (
            pick
            and pick[1] >= _REPLACE_RATIO
            and _norm(pick[0]) != _norm(ln.text)
            and abs(len(_norm(pick[0]).split()) - len(_norm(ln.text).split())) <= _MAX_TOKEN_DELTA
        ):
            new_lines.append(LyricLine(start=ln.start, text=pick[0]))
            replaced += 1
        else:
            new_lines.append(ln)
    if replaced == 0:
        return None
    return new_lines, replaced, len(matched)


def auto_correct(
    trans_lines: list[LyricLine], title: str, artist: str, duration: float = 0.0
) -> Correction:
    """Best validated correction of a transcription, or the lines unchanged."""
    if not trans_lines:
        return Correction(lines=list(trans_lines), method="none")
    try:
        # Try every synced candidate: duration ranking alone can put a
        # wrong-timeline entry first, and only alignment can tell them apart.
        first_usable: list[LyricLine] = []
        for lrc in search_synced_candidates(title, artist, duration):
            ref_synced = parse_lrc(lrc)
            if len(ref_synced) < _MIN_REF_LINES:
                continue
            if not first_usable:
                first_usable = ref_synced
            aligned = _aligned_from_synced(trans_lines, ref_synced, duration)
            if aligned:
                lines, offset, anchors = aligned
                return Correction(lines, "synced_aligned", offset=offset, anchors=anchors)

        plain = search_plain(title, artist, duration)
        # A synced source that failed alignment (different cut) still carries
        # the right words — usable as a plain-text reference.
        ref_texts = plain.splitlines() if plain else [ln.text for ln in first_usable]
        if ref_texts:
            corrected = _corrected_from_plain(trans_lines, ref_texts)
            if corrected:
                lines, replaced, anchors = corrected
                return Correction(lines, "plain_corrected", replaced=replaced, anchors=anchors)
    except Exception:
        log.exception("auto-correction failed; keeping raw transcription")
    return Correction(lines=list(trans_lines), method="none")
