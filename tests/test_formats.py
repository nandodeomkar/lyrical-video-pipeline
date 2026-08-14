"""Four-format lyric writers — FR-007, exact specs from PRD §7."""

import json

from pipeline.formats import derive_end_times, write_all
from pipeline.lyrics import LyricLine

LINES = [
    LyricLine(start=12.0, text="First line of the lyrics"),
    LyricLine(start=17.25, text="Second line of the lyrics"),
    LyricLine(start=21.5, text="Third line"),
]
TRACK_END = 228.0  # 3:48


def test_end_times_derived_from_next_start():
    timed = derive_end_times(LINES, TRACK_END)
    assert timed[0] == (12.0, 17.25, "First line of the lyrics")
    assert timed[1] == (17.25, 21.5, "Second line of the lyrics")


def test_last_line_ends_at_track_end():
    timed = derive_end_times(LINES, TRACK_END)
    assert timed[-1] == (21.5, 228.0, "Third line")


def test_unknown_duration_gets_fallback_tail():
    timed = derive_end_times(LINES, 0.0)
    assert timed[-1][1] == 21.5 + 3.0


def test_txt_format(tmp_path):
    paths = write_all(LINES, TRACK_END, tmp_path, "Song - Artist")
    content = paths["txt"].read_text(encoding="utf-8")
    assert content == (
        "[00:12] First line of the lyrics\n"
        "[00:17] Second line of the lyrics\n"
        "[00:22] Third line\n"  # 21.5 rounds to 22
    )


def test_srt_format(tmp_path):
    paths = write_all(LINES, TRACK_END, tmp_path, "Song - Artist")
    blocks = paths["srt"].read_text(encoding="utf-8").split("\n\n")
    assert blocks[0] == "1\n00:00:12,000 --> 00:00:17,250\nFirst line of the lyrics"
    assert blocks[2].startswith("3\n00:00:21,500 --> 00:03:48,000\nThird line")


def test_lrc_format(tmp_path):
    paths = write_all(LINES, TRACK_END, tmp_path, "Song - Artist")
    lines = paths["lrc"].read_text(encoding="utf-8").splitlines()
    assert lines[0] == "[00:12.00]First line of the lyrics"
    assert lines[1] == "[00:17.25]Second line of the lyrics"


def test_json_format(tmp_path):
    paths = write_all(LINES, TRACK_END, tmp_path, "Song - Artist")
    data = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert data == [
        {"start": 12.0, "end": 17.25, "text": "First line of the lyrics"},
        {"start": 17.25, "end": 21.5, "text": "Second line of the lyrics"},
        {"start": 21.5, "end": 228.0, "text": "Third line"},
    ]


def test_all_four_files_share_base_name(tmp_path):
    paths = write_all(LINES, TRACK_END, tmp_path, "Song - Artist")
    assert sorted(paths) == ["json", "lrc", "srt", "txt"]
    assert all(p.stem == "Song - Artist" for p in paths.values())
