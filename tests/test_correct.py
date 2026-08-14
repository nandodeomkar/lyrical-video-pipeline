"""Auto-correction of transcriptions against online lyrics (R-004, NFR-010)."""

import pipeline.correct as correct
from pipeline.correct import auto_correct
from pipeline.lyrics import LyricLine

# "Online" reference on an album-cut timeline (times in seconds).
REF = [
    (10.0, "It's been so long"),
    (14.0, "That I haven't seen your face"),
    (18.0, "I'm tryna be strong"),
    (22.0, "But the strength I have is washing away"),
    (26.0, "It won't be long before I get you by my side"),
    (30.0, "And just hold you, tease you, squeeze you"),
    (34.0, "Tell you what's been on my mind"),
    (38.0, "I wanna make up right now na na"),
    (42.0, "Wish we never broke up right now na na"),
    (46.0, "We need to link up right now na na"),
    (50.0, "Cause you are the apple of my eye"),
    (54.0, "Till I get you back I'm gonna cry"),
]

# What the transcription "heard" — same lines with typical mishearings.
HEARD = [
    "It's been so long",
    "That I haven't seen your face",
    "I'm trying to be strong",
    "But the strength I have is washing away",
    "It won't be long before I get you by my side",
    "And just hold you, tease you, squeeze you",
    "Tell you what's been on my mind",
    "I wanna make a bride na na na",
    "Miss we never broke up right now now now",
    "We need to link up right now now now",
    "Cause you are the apple of my eye",
    "Till I get you back I'm gonna try",
]


def _lrc(entries):
    return "\n".join(f"[{int(t // 60):02d}:{t % 60:05.2f}] {text}" for t, text in entries)


def _trans(offset=56.7, jitter=0.3, texts=HEARD):
    return [
        LyricLine(start=t + offset + (jitter if i % 2 else -jitter), text=texts[i])
        for i, (t, _) in enumerate(REF)
    ]


def _searches(monkeypatch, synced=None, plain=None):
    cands = [synced] if isinstance(synced, str) else list(synced or [])
    monkeypatch.setattr(correct, "search_synced_candidates", lambda *a, **k: cands)
    monkeypatch.setattr(correct, "search_plain", lambda *a, **k: plain)


def test_synced_alignment_adopts_shifted_reference(monkeypatch):
    _searches(monkeypatch, synced=_lrc(REF))
    res = auto_correct(_trans(), "Song", "Artist", duration=300.0)
    assert res.method == "synced_aligned"
    assert abs(res.offset - 56.7) < 0.5
    assert res.anchors >= 6
    assert len(res.lines) == len(REF)
    # Words come from the reference (mishearings gone)...
    assert res.lines[7].text == "I wanna make up right now na na"
    assert res.lines[8].text == "Wish we never broke up right now na na"
    # ...timing is the reference shifted onto our audio's timeline.
    assert abs(res.lines[0].start - (10.0 + 56.7)) < 0.5


def test_drifting_offset_means_wrong_cut_and_is_rejected(monkeypatch):
    # Per-line offset grows 2s per line — a different cut, no constant shift.
    drifting = [
        LyricLine(start=t + 56.7 + i * 2.0, text=text)
        for i, (t, text) in enumerate(REF)
    ]
    _searches(monkeypatch, synced=_lrc(REF))
    res = auto_correct(drifting, "Song", "Artist", duration=300.0)
    # Texts already match the reference, so the plain fallback changes nothing.
    assert res.method == "none"
    assert [ln.text for ln in res.lines] == [text for _, text in REF]


def test_wrong_song_reference_leaves_transcription_untouched(monkeypatch):
    wrong = [
        (t, text)
        for t, text in zip(
            (t for t, _ in REF),
            [
                "Tractor rides at midnight",
                "Dancing on the tailgate in the rain",
                "Whiskey on the rocks for two",
                "Mama said the crops are coming in",
                "Dusty roads and radio static",
                "Boots are made for kicking back",
                "Sunset over the silo tonight",
                "Catfish frying on the open flame",
                "Granddaddy's old guitar still plays",
                "County fair lights spinning round",
                "Mason jars and fireflies",
                "Front porch swing till morning comes",
            ],
        )
    ]
    trans = _trans()
    _searches(monkeypatch, synced=_lrc(wrong), plain="\n".join(t for _, t in wrong))
    res = auto_correct(trans, "Song", "Artist", duration=300.0)
    assert res.method == "none"
    assert [ln.text for ln in res.lines] == HEARD


def test_plain_correction_fixes_misheard_lines_keeps_timing(monkeypatch):
    plain = "[Chorus]\n" + "\n".join(text for _, text in REF)
    trans = _trans() + [LyricLine(start=200.0, text="I")]  # stray fragment
    _searches(monkeypatch, plain=plain)
    res = auto_correct(trans, "Song", "Artist", duration=300.0)
    assert res.method == "plain_corrected"
    assert res.replaced >= 3
    assert res.lines[7].text == "I wanna make up right now na na"
    assert res.lines[8].text == "Wish we never broke up right now na na"
    assert res.lines[11].text == "Till I get you back I'm gonna cry"
    # Timing stays the transcription's own.
    assert res.lines[7].start == trans[7].start
    # Fragments below the phrase threshold are never replaced.
    assert res.lines[12].text == "I"


def test_second_candidate_aligns_when_first_drifts(monkeypatch):
    # The duration-ranked top candidate has a drifting timeline (different
    # cut); the album-cut candidate behind it aligns — it must win.
    drifting = _lrc([(t * 1.3, text) for t, text in REF])
    good = _lrc(REF)
    _searches(monkeypatch, synced=[drifting, good])
    res = auto_correct(_trans(), "Song", "Artist", duration=300.0)
    assert res.method == "synced_aligned"
    assert abs(res.offset - 56.7) < 0.5


def test_plain_replacement_rejects_longer_spanning_lines(monkeypatch):
    # A reference line that merges two sung lines must not replace either
    # half — that would duplicate words across adjacent output lines.
    plain = "\n".join(text for _, text in REF) + "\nWhy'd you go and haven't seen my girl since then"
    trans = _trans() + [LyricLine(start=150.0, text="And haven't seen my girl since then")]
    _searches(monkeypatch, plain=plain)
    res = auto_correct(trans, "Song", "Artist", duration=300.0)
    assert res.method == "plain_corrected"
    assert res.lines[12].text == "And haven't seen my girl since then"  # untouched


def test_unaligned_synced_text_still_corrects_words(monkeypatch):
    # Synced source exists but its timeline drifts (different cut): its text
    # is reused as a plain reference; transcription timing is kept.
    drifting_ref = [(t * 1.3, text) for t, text in REF]
    trans = _trans()
    _searches(monkeypatch, synced=_lrc(drifting_ref), plain=None)
    res = auto_correct(trans, "Song", "Artist", duration=300.0)
    assert res.method == "plain_corrected"
    assert res.lines[7].text == "I wanna make up right now na na"
    assert res.lines[7].start == trans[7].start


def test_lines_shifted_before_zero_are_dropped(monkeypatch):
    # Our audio starts mid-song: an intro-only reference line would land at a
    # negative timestamp after shifting and must be dropped.
    ref = [(2.0, "Ooh yeah this is the intro hook")] + [(t + 20, x) for t, x in REF]
    trans = [LyricLine(start=t + 20 - 10.0, text=x) for t, x in REF]
    _searches(monkeypatch, synced=_lrc(ref))
    res = auto_correct(trans, "Song", "Artist", duration=0.0)
    assert res.method == "synced_aligned"
    assert len(res.lines) == len(REF)  # intro line dropped
    assert res.lines[0].text == "It's been so long"
    assert abs(res.lines[0].start - 20.0) < 0.1


def test_empty_transcription_is_a_noop():
    res = auto_correct([], "Song", "Artist")
    assert res.method == "none"
    assert res.lines == []


def test_lookup_exception_keeps_raw_transcription(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network meltdown")

    monkeypatch.setattr(correct, "search_synced_candidates", boom)
    trans = _trans()
    res = auto_correct(trans, "Song", "Artist", duration=300.0)
    assert res.method == "none"
    assert [ln.text for ln in res.lines] == HEARD
