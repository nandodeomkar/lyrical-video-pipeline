"""Lyrics lookup (FR-005, R-006 wrong-match mitigation) + LRC parsing."""

import pipeline.lyrics as lyrics
from pipeline.lyrics import (
    _title_variants,
    parse_lrc,
    search_plain,
    search_synced,
    search_synced_candidates,
)


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _no_aggregator(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("aggregator should not be called")

    monkeypatch.setattr(lyrics.syncedlyrics, "search", boom)


def test_title_variants_full_then_stripped():
    assert _title_variants("Right Now (Na Na Na)") == ["Right Now (Na Na Na)", "Right Now"]
    assert _title_variants("Plain Title") == ["Plain Title"]
    # A title that is only a bracket group has no usable stripped form.
    assert _title_variants("(Na Na Na)") == ["(Na Na Na)"]


def test_lrclib_hit_wins_without_aggregator(monkeypatch):
    monkeypatch.setattr(
        lyrics.requests,
        "get",
        lambda *a, **k: _FakeResp([{"syncedLyrics": "[00:01] hi", "duration": 200}]),
    )
    _no_aggregator(monkeypatch)
    assert search_synced("Song", "Artist") == "[00:01] hi"


def test_lrclib_picks_closest_duration(monkeypatch):
    data = [
        {"syncedLyrics": "[00:01] album cut", "duration": 241},
        {"syncedLyrics": "[00:01] video cut", "duration": 300},
    ]
    monkeypatch.setattr(lyrics.requests, "get", lambda *a, **k: _FakeResp(data))
    _no_aggregator(monkeypatch)
    assert search_synced("Song", "Artist", duration=295.0) == "[00:01] video cut"
    assert search_synced("Song", "Artist", duration=240.0) == "[00:01] album cut"


def test_lrclib_skips_instrumental_and_empty_entries(monkeypatch):
    data = [
        {"syncedLyrics": None, "instrumental": True, "duration": 200},
        {"syncedLyrics": "   ", "duration": 200},
    ]
    monkeypatch.setattr(lyrics.requests, "get", lambda *a, **k: _FakeResp(data))
    monkeypatch.setattr(lyrics.syncedlyrics, "search", lambda *a, **k: None)
    assert search_synced("Song", "Artist") is None


def test_stripped_variant_rescues_aggregator_miss(monkeypatch):
    # LRCLIB unreachable; the free-text aggregator only matches once the
    # "(Na Na Na)" qualifier is dropped — the observed R-006 failure.
    def lrclib_down(*args, **kwargs):
        raise ConnectionError("offline")

    def fake_aggregator(query, **kwargs):
        return "[00:01] right song" if query == "Right Now Akon" else None

    monkeypatch.setattr(lyrics.requests, "get", lrclib_down)
    monkeypatch.setattr(lyrics.syncedlyrics, "search", fake_aggregator)
    assert search_synced("Right Now (Na Na Na)", "Akon") == "[00:01] right song"


def test_aggregator_provider_error_falls_through_to_next_variant(monkeypatch):
    def lrclib_down(*args, **kwargs):
        raise ConnectionError("offline")

    def flaky_aggregator(query, **kwargs):
        if "(" in query:
            raise RuntimeError("provider hiccup")
        return "[00:01] rescued"

    monkeypatch.setattr(lyrics.requests, "get", lrclib_down)
    monkeypatch.setattr(lyrics.syncedlyrics, "search", flaky_aggregator)
    assert search_synced("Song (Remix)", "Artist") == "[00:01] rescued"


def test_synced_candidates_ranked_by_duration_proximity(monkeypatch):
    data = [
        {"syncedLyrics": "[00:01] album cut", "duration": 241},
        {"syncedLyrics": "[00:01] video cut", "duration": 300},
    ]
    monkeypatch.setattr(lyrics.requests, "get", lambda *a, **k: _FakeResp(data))
    monkeypatch.setattr(lyrics.syncedlyrics, "search", lambda *a, **k: None)
    cands = search_synced_candidates("Song", "Artist", duration=295.0)
    assert cands == ["[00:01] video cut", "[00:01] album cut"]


def test_search_plain_uses_plain_field(monkeypatch):
    data = [{"plainLyrics": "the words", "syncedLyrics": None, "duration": 100}]
    monkeypatch.setattr(lyrics.requests, "get", lambda *a, **k: _FakeResp(data))
    _no_aggregator(monkeypatch)
    assert search_plain("Song", "Artist") == "the words"


def test_empty_query_returns_none_without_network(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("no lookup should happen for an empty query")

    monkeypatch.setattr(lyrics.requests, "get", no_network)
    _no_aggregator(monkeypatch)
    assert search_synced("", "") is None
    assert search_plain("  ", " ") is None


def test_basic_line():
    lines = parse_lrc("[00:12]Hello world")
    assert len(lines) == 1
    assert lines[0].start == 12.0
    assert lines[0].text == "Hello world"


def test_centiseconds_and_milliseconds():
    lines = parse_lrc("[00:12.34]a\n[00:13.345]b\n[00:14:56]c")
    assert [round(ln.start, 3) for ln in lines] == [12.34, 13.345, 14.56]


def test_multiple_timestamps_one_line():
    lines = parse_lrc("[00:10][01:20]Chorus")
    assert [(ln.start, ln.text) for ln in lines] == [(10.0, "Chorus"), (80.0, "Chorus")]


def test_metadata_tags_skipped():
    lines = parse_lrc("[ar:Artist]\n[ti:Title]\n[length:3:50]\n[00:05]Real line")
    assert len(lines) == 1
    assert lines[0].text == "Real line"


def test_empty_text_lines_dropped():
    lines = parse_lrc("[00:05]\n[00:10]Sung line\n\n")
    assert [ln.text for ln in lines] == ["Sung line"]


def test_enhanced_lrc_word_tags_stripped():
    lines = parse_lrc("[00:05]<00:05.10>Hello <00:05.90>there")
    assert lines[0].text == "Hello there"


def test_output_sorted_by_time():
    lines = parse_lrc("[01:00]second\n[00:30]first")
    assert [ln.text for ln in lines] == ["first", "second"]
