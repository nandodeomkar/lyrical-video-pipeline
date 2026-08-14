"""Word-level line re-segmentation — fixes large-v3 merging whole choruses."""

from pipeline.transcribe_worker import MAX_LINE_CHARS, split_into_lines


def _w(word, start, end):
    return {"word": word, "start": start, "end": end}


def _phrase(text, t0, word_gap=0.02, dur=0.25):
    """Words sung continuously (tiny intra-phrase gaps); returns (words, t_end)."""
    words, t = [], t0
    for token in text.split():
        words.append(_w(token, round(t, 3), round(t + dur, 3)))
        t += dur + word_gap
    return words, t


def test_hard_gap_starts_new_line():
    a, t = _phrase("We're no strangers to love", 18.7)
    b, _ = _phrase("You know the rules and so do I", t + 1.5)  # gap > HARD_GAP_S
    lines = split_into_lines(a + b)
    assert [ln["text"] for ln in lines] == [
        "We're no strangers to love",
        "You know the rules and so do I",
    ]


def test_sentence_punctuation_starts_new_line():
    a, t = _phrase("You wouldn't get this from any other guy.", 31.0)
    b, _ = _phrase("I just wanna tell you", t + 0.1)  # tiny gap, but '.' before it
    lines = split_into_lines(a + b)
    assert len(lines) == 2


def test_merged_chorus_splits_at_breath_gaps():
    # Three phrases sung back-to-back with only breath gaps (~0.3s) between —
    # exactly the merged-chorus failure observed with large-v3.
    p1, t1 = _phrase("Never gonna give you up", 40.0)
    p2, t2 = _phrase("Never gonna let you down", t1 + 0.3)
    p3, _ = _phrase("Never gonna run around and desert you", t2 + 0.35)
    lines = split_into_lines(p1 + p2 + p3)
    assert [ln["text"] for ln in lines] == [
        "Never gonna give you up",
        "Never gonna let you down",
        "Never gonna run around and desert you",
    ]
    assert all(len(ln["text"]) <= MAX_LINE_CHARS for ln in lines)


def test_line_times_come_from_first_and_last_word():
    words, _ = _phrase("short line here", 12.0)
    lines = split_into_lines(words)
    assert lines[0]["start"] == words[0]["start"]
    assert lines[0]["end"] == words[-1]["end"]


def test_missing_word_times_interpolated():
    words = [
        _w("timed", 10.0, 10.3),
        _w("untimed", None, None),  # alignment skips digits etc.
        _w("again", 10.8, 11.1),
    ]
    lines = split_into_lines(words)
    assert lines[0]["text"] == "timed untimed again"


def test_empty_input():
    assert split_into_lines([]) == []
