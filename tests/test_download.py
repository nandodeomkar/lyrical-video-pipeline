"""Title-guess cleaning (FR-003/FR-015) and URL validation (FR-002). Offline."""

from pathlib import Path

import pytest

import pipeline.download as download
from pipeline.download import clean_title, validate_url


def test_strips_official_video_suffix():
    assert clean_title("Never Gonna Give You Up (Official Video)", "Rick Astley") == \
        "Never Gonna Give You Up"


def test_strips_stacked_noise_groups():
    assert clean_title(
        "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)",
        "Rick Astley",
    ) == "Never Gonna Give You Up"


def test_strips_artist_prefix_case_insensitive():
    assert clean_title("RICK ASTLEY - Together Forever", "Rick Astley") == "Together Forever"


def test_plain_title_untouched():
    assert clean_title("Blinding Lights", "The Weeknd") == "Blinding Lights"


def test_meaningful_brackets_kept():
    assert clean_title("Layla (Acoustic)", "Eric Clapton") == "Layla (Acoustic)"


def test_all_noise_falls_back_to_original():
    assert clean_title("(Official Video)", "X") == "(Official Video)"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "http://youtube.com/watch?v=dQw4w9WgXcQ&list=PL123",  # single video + list param
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=42",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "  https://www.youtube.com/watch?v=dQw4w9WgXcQ  ",  # surrounding whitespace
    ],
)
def test_valid_youtube_urls_pass(url):
    assert validate_url(url) is None


def test_download_video_requests_capped_video_only_stream(tmp_path, monkeypatch):
    # M5: video-only (the MP3 is the audio track), ≤1080p, MP4/h264 preferred.
    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            Path(captured["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"vid")
            return {"ext": "mp4"}

        def prepare_filename(self, info):
            return captured["outtmpl"].replace("%(ext)s", "mp4")

    monkeypatch.setattr(download.yt_dlp, "YoutubeDL", FakeYDL)
    out = download.download_video("https://youtu.be/dQw4w9WgXcQ", tmp_path)
    assert out.name == "source_video.mp4"
    assert out.read_bytes() == b"vid"
    assert captured["format"] == (
        "bestvideo[height<=1080][ext=mp4]/bestvideo[height<=1080]/bestvideo"
    )
    assert "bestaudio" not in captured["format"]  # video-only stream
    assert captured["noplaylist"] is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url at all",
        "www.youtube.com/watch?v=dQw4w9WgXcQ",  # missing scheme
        "ftp://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://vimeo.com/123456",
        "https://www.youtube.com/watch",  # no video id
        "https://www.youtube.com/watch?v=abc",  # id too short
        "https://youtu.be/",
        "https://www.youtube.com/playlist?list=PL123456789",  # playlist, not a video
        "https://www.youtube.com/@SomeChannel",
        "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
        "https://fakeyoutube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_invalid_urls_rejected_with_reason(url):
    problem = validate_url(url)
    assert isinstance(problem, str) and problem  # readable reason (FR-002)
