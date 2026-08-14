"""Lyric-video render driver (M4 + M5 + M6 scope extensions). Offline — Remotion mocked."""

import colorsys
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import pipeline.video as video
from pipeline.video import (
    DEFAULT_PALETTE,
    VideoSetupError,
    _build_command,
    _props_for,
    _tune_color,
    _versioned_mp4,
    extract_palette,
    fetch_video,
    find_run_url,
    find_song_files,
    find_video_file,
    parse_base,
    render_lyric_video,
)

LINES = [
    {"start": 10.0, "end": 14.0, "text": "First line"},
    {"start": 14.0, "end": 200.5, "text": "Last line"},
]


def _song_folder(tmp_path, base="Song - Artist", lines=LINES):
    (tmp_path / f"{base}.mp3").write_bytes(b"mp3")
    (tmp_path / f"{base}.json").write_text(json.dumps(lines), encoding="utf-8")
    return tmp_path


def _run_log(tmp_path, records):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / "runs.jsonl").write_text("\n".join(records), encoding="utf-8")
    return log_dir


def test_find_song_files_picks_pair(tmp_path):
    _song_folder(tmp_path)
    (tmp_path / "Song - Artist.txt").write_text("x")  # other formats ignored
    base, mp3, json_path = find_song_files(tmp_path)
    assert base == "Song - Artist"
    assert mp3.name == "Song - Artist.mp3"
    assert json_path.name == "Song - Artist.json"


def test_find_song_files_prefers_newest_version(tmp_path):
    _song_folder(tmp_path, "Song - Artist")
    time.sleep(0.05)  # mtime tiebreaker
    _song_folder(tmp_path, "Song - Artist (2)")
    base, _, _ = find_song_files(tmp_path)
    assert base == "Song - Artist (2)"


def test_find_song_files_ignores_json_without_mp3(tmp_path):
    (tmp_path / "orphan.json").write_text("[]")
    with pytest.raises(FileNotFoundError):
        find_song_files(tmp_path)


def test_parse_base_splits_title_artist_and_strips_version():
    assert parse_base("Right Now (Na Na Na) - Akon") == ("Right Now (Na Na Na)", "Akon")
    assert parse_base("Song - Artist (2)") == ("Song", "Artist")
    assert parse_base("NoArtistHere") == ("NoArtistHere", "")


def test_props_duration_from_last_line_end(tmp_path):
    folder = _song_folder(tmp_path)
    props = _props_for(folder / "Song - Artist.json", "Song", "Artist", "Song - Artist.mp3")
    assert props["duration"] == 200.5
    assert props["audioFile"] == "Song - Artist.mp3"
    assert len(props["lines"]) == 2


def test_props_rejects_empty_lyrics(tmp_path):
    folder = _song_folder(tmp_path, lines=[])
    with pytest.raises(ValueError):
        _props_for(folder / "Song - Artist.json", "Song", "Artist", "x.mp3")


def test_versioned_mp4_never_overwrites(tmp_path):
    assert _versioned_mp4(tmp_path, "Song - Artist").name == "Song - Artist.mp4"
    (tmp_path / "Song - Artist.mp4").write_bytes(b"")
    assert _versioned_mp4(tmp_path, "Song - Artist").name == "Song - Artist (2).mp4"


def test_build_command_is_explicit(tmp_path):
    cmd = _build_command(tmp_path / "out.mp4", tmp_path / "props.json", tmp_path, "0-120")
    assert cmd[0] == "node"
    assert "render" in cmd and "LyricVideo" in cmd
    assert str(tmp_path / "out.mp4") in cmd
    assert f"--props={tmp_path / 'props.json'}" in cmd
    assert f"--public-dir={tmp_path}" in cmd
    assert "--frames=0-120" in cmd


def test_build_command_takes_composition(tmp_path):
    cmd = _build_command(tmp_path / "o.mp4", tmp_path / "p.json", tmp_path, None, "VideoPanel")
    assert "VideoPanel" in cmd and "LyricVideo" not in cmd


def test_build_command_default_is_gpu_with_load_guardrails(tmp_path):
    cmd = _build_command(tmp_path / "o.mp4", tmp_path / "p.json", tmp_path, None)
    assert "--gl=angle" in cmd
    assert "--chrome-mode=chrome-for-testing" in cmd  # headless shell has no GPU
    assert "--concurrency=4" in cmd
    assert any(a.startswith("--offthreadvideo-cache-size-in-bytes=") for a in cmd)


def test_build_command_cpu_fallback_keeps_guardrails(tmp_path):
    cmd = _build_command(
        tmp_path / "o.mp4", tmp_path / "p.json", tmp_path, None, gpu=False, concurrency=2
    )
    assert not any(a.startswith(("--gl", "--chrome-mode")) for a in cmd)
    assert "--concurrency=2" in cmd


# --- M5: source-video discovery, run-log URL lookup, on-demand fetch ---------


def test_find_video_file_newest_for_exact_base(tmp_path):
    (tmp_path / "Song - Artist.video.webm").write_bytes(b"old")
    time.sleep(0.05)
    (tmp_path / "Song - Artist.video.mp4").write_bytes(b"new")
    (tmp_path / "Song - Artist (2).video.mp4").write_bytes(b"other base")
    assert find_video_file(tmp_path, "Song - Artist").name == "Song - Artist.video.mp4"
    assert find_video_file(tmp_path, "Song - Artist (2)").name == "Song - Artist (2).video.mp4"


def test_find_video_file_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="source video"):
        find_video_file(tmp_path, "Song - Artist")


def test_find_run_url_newest_successful_match_skips_junk(tmp_path):
    log_dir = _run_log(tmp_path, [
        json.dumps({"url": "https://old", "title": "Song", "artist": "Artist", "success": True}),
        "{this line is not json",
        json.dumps({"url": "https://failed", "title": "Song", "artist": "Artist", "success": False}),
        json.dumps({"url": "https://new", "title": "Song", "artist": "Artist", "success": True}),
    ])
    assert find_run_url(log_dir, "Song - Artist") == "https://new"
    assert find_run_url(log_dir, "Song - Artist (3)") == "https://new"  # version stripped
    assert find_run_url(log_dir, "Other - Artist") is None


def test_find_run_url_matches_sanitized_folder_name(tmp_path):
    # Folder bases are sanitized (FR-009); log titles keep the raw characters.
    log_dir = _run_log(tmp_path, [
        json.dumps({"url": "https://u", "title": "What? Song", "artist": "A*B", "success": True}),
    ])
    assert find_run_url(log_dir, "What Song - AB") == "https://u"


def test_find_run_url_without_log_file(tmp_path):
    assert find_run_url(tmp_path, "Song - Artist") is None


def test_fetch_video_returns_existing_without_downloading(tmp_path, monkeypatch):
    _song_folder(tmp_path)
    (tmp_path / "Song - Artist.video.mp4").write_bytes(b"v")

    def boom(url, work_dir):
        raise AssertionError("download_video must not be called")

    monkeypatch.setattr(video, "download_video", boom)
    assert fetch_video(tmp_path).name == "Song - Artist.video.mp4"


def test_fetch_video_downloads_via_run_log(tmp_path, monkeypatch):
    folder = tmp_path / "Song - Artist"
    folder.mkdir()
    _song_folder(folder)
    log_dir = _run_log(tmp_path, [
        json.dumps({"url": "https://yt", "title": "Song", "artist": "Artist", "success": True}),
    ])

    def fake_download(url, work_dir):
        assert url == "https://yt"
        p = Path(work_dir) / "source_video.webm"
        p.write_bytes(b"vid")
        return p

    monkeypatch.setattr(video, "download_video", fake_download)
    out = fetch_video(folder, log_dir)
    assert out == folder / "Song - Artist.video.webm"
    assert out.read_bytes() == b"vid"


def test_fetch_video_without_recoverable_url_raises(tmp_path):
    folder = tmp_path / "Song - Artist"
    folder.mkdir()
    _song_folder(folder)
    with pytest.raises(RuntimeError, match="re-run the song"):
        fetch_video(folder, tmp_path / "no-logs-here")


# --- mocked Remotion renders --------------------------------------------------


class _FakeProc:
    last_cmd = None
    last_props = None
    last_kwargs = None

    def __init__(self, cmd, **kwargs):
        type(self).last_cmd = cmd
        type(self).last_kwargs = kwargs
        self.kwargs = kwargs
        # The output target is the positional arg right after the composition id.
        comp = next(c for c in ("LyricVideo", "VideoPanel") if c in cmd)
        out = cmd[cmd.index(comp) + 1]
        props_arg = next(a for a in cmd if a.startswith("--props="))
        type(self).last_props = json.loads(
            Path(props_arg.removeprefix("--props=")).read_text(encoding="utf-8")
        )
        Path(out).write_bytes(b"fake mp4")
        self.stdout = io.StringIO("Rendered 1/2\nRendered 2/2\nEncoded 2/2\n")

    def wait(self):
        return 0


def _mock_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "_CLI_JS", tmp_path / "cli.js")
    (tmp_path / "cli.js").write_text("")
    monkeypatch.setattr(video.subprocess, "Popen", _FakeProc)
    # Keep render tests hermetic: no real ffprobe/ffmpeg on fake video bytes.
    # Palette-specific tests re-patch this with their own fakes.
    monkeypatch.setattr(video, "extract_palette", lambda p: None)


def test_render_flow_with_mocked_subprocess(tmp_path, monkeypatch):
    folder = _song_folder(tmp_path)
    _mock_cli(tmp_path, monkeypatch)
    seen = []
    out = render_lyric_video(folder, on_progress=seen.append)
    assert out == folder / "Song - Artist.mp4"
    assert out.read_bytes() == b"fake mp4"
    assert seen == ["Rendered 1/2", "Rendered 2/2", "Encoded 2/2"]


def test_render_runs_below_normal_priority(tmp_path, monkeypatch):
    # The render must never starve the rest of the machine (2026-06-11 fix).
    folder = _song_folder(tmp_path)
    _mock_cli(tmp_path, monkeypatch)
    render_lyric_video(folder)
    expected = getattr(video.subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    assert _FakeProc.last_kwargs["creationflags"] == expected


def test_render_passes_gpu_and_concurrency_through(tmp_path, monkeypatch):
    folder = _song_folder(tmp_path)
    _mock_cli(tmp_path, monkeypatch)
    render_lyric_video(folder, gpu=False, concurrency=2)
    assert "--concurrency=2" in _FakeProc.last_cmd
    assert not any(a.startswith("--gl") for a in _FakeProc.last_cmd)
    render_lyric_video(folder)
    assert "--gl=angle" in _FakeProc.last_cmd
    assert "--concurrency=4" in _FakeProc.last_cmd


def test_render_resolves_relative_song_dir(tmp_path, monkeypatch):
    # Regression: the CLI runs with cwd=video/, so a relative song dir must be
    # made absolute or --public-dir points at a nonexistent folder (audio 404s).
    nested = tmp_path / "Output" / "Song - Artist"
    nested.mkdir(parents=True)
    _song_folder(nested)
    _mock_cli(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    render_lyric_video(Path("Output") / "Song - Artist")
    public_arg = next(a for a in _FakeProc.last_cmd if a.startswith("--public-dir="))
    assert Path(public_arg.removeprefix("--public-dir=")).is_absolute()


def test_render_fails_clearly_without_cli(tmp_path, monkeypatch):
    folder = _song_folder(tmp_path)
    monkeypatch.setattr(video, "_CLI_JS", tmp_path / "missing" / "cli.js")
    with pytest.raises(VideoSetupError):
        render_lyric_video(folder)


def test_render_panel_layout_full_flow(tmp_path, monkeypatch):
    folder = _song_folder(tmp_path)
    (tmp_path / "Song - Artist.video.mp4").write_bytes(b"v")
    _mock_cli(tmp_path, monkeypatch)
    out = render_lyric_video(folder, layout="panel")
    assert out == folder / "Song - Artist [video+lyrics].mp4"
    assert "VideoPanel" in _FakeProc.last_cmd and "LyricVideo" not in _FakeProc.last_cmd
    assert _FakeProc.last_props["videoFile"] == "Song - Artist.video.mp4"
    assert _FakeProc.last_props["audioFile"] == "Song - Artist.mp3"


def test_render_panel_output_never_overwrites(tmp_path, monkeypatch):
    folder = _song_folder(tmp_path)
    (tmp_path / "Song - Artist.video.mp4").write_bytes(b"v")
    (tmp_path / "Song - Artist [video+lyrics].mp4").write_bytes(b"old")
    _mock_cli(tmp_path, monkeypatch)
    out = render_lyric_video(folder, layout="panel")
    assert out.name == "Song - Artist [video+lyrics] (2).mp4"
    assert (tmp_path / "Song - Artist [video+lyrics].mp4").read_bytes() == b"old"


def test_render_panel_requires_source_video(tmp_path, monkeypatch):
    folder = _song_folder(tmp_path)
    monkeypatch.setattr(video, "_CLI_JS", tmp_path / "cli.js")
    (tmp_path / "cli.js").write_text("")
    with pytest.raises(FileNotFoundError, match="source video"):
        render_lyric_video(folder, layout="panel")


# --- M6: palette extraction + colorwash props ----------------------------------


def _hls(hex_color):
    rgb = tuple(int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(*rgb)


def _fake_ffmpeg(monkeypatch, samples, duration="200.0\n"):
    """ffprobe answers `duration`; each ffmpeg call pops the next rgb24 bytes."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffprobe":
            return SimpleNamespace(returncode=0, stdout=duration, stderr="")
        return SimpleNamespace(returncode=0, stdout=samples.pop(0), stderr=b"")

    monkeypatch.setattr(video.subprocess, "run", fake_run)
    return calls


def test_tune_color_clamps_into_text_safe_band():
    # Near-black, near-white, and gray inputs all land in the dark wash band.
    for rgb in [(0, 0, 0), (255, 255, 255), (128, 128, 128), (250, 30, 40)]:
        h, l, s = _hls(_tune_color(rgb))
        assert 0.15 <= l <= 0.35, f"{rgb} -> lightness {l}"
        assert s >= 0.34, f"{rgb} -> saturation {s}"


def test_tune_color_preserves_hue():
    in_h, _, _ = colorsys.rgb_to_hls(250 / 255, 30 / 255, 40 / 255)
    out_h, _, _ = _hls(_tune_color((250, 30, 40)))
    assert abs(in_h - out_h) < 0.02


def test_default_palette_is_inside_the_tuned_band():
    for color in DEFAULT_PALETTE:
        _, l, s = _hls(color)
        assert 0.15 <= l <= 0.35 and s >= 0.34


def test_extract_palette_samples_five_positions_and_tunes(tmp_path, monkeypatch):
    # red, near-red (dropped), green, near-green (dropped), blue -> 3 colors,
    # and the duplicates force all five timestamps to be sampled.
    samples = [bytes(c) for c in ([200, 30, 30], [210, 40, 40], [30, 200, 30], [40, 210, 40], [30, 30, 200])]
    calls = _fake_ffmpeg(monkeypatch, samples)
    palette = extract_palette(tmp_path / "v.mp4")
    assert palette is not None and len(palette) == 3
    for color in palette:
        _, l, s = _hls(color)
        assert 0.15 <= l <= 0.35 and s >= 0.34
    # 10/30/50/70/90% of the 200s duration
    seek_times = [c[c.index("-ss") + 1] for c in calls if c[0] == "ffmpeg"]
    assert seek_times == ["20.000", "60.000", "100.000", "140.000", "180.000"]


def test_extract_palette_dedupes_similar_hues(tmp_path, monkeypatch):
    samples = [bytes([200, 30, 30])] * 5  # one hue, five frames
    _fake_ffmpeg(monkeypatch, samples)
    palette = extract_palette(tmp_path / "v.mp4")
    assert palette is not None and len(palette) == 1


def test_extract_palette_never_raises(tmp_path, monkeypatch):
    def boom(cmd, **kwargs):
        raise FileNotFoundError("ffprobe is not installed")

    monkeypatch.setattr(video.subprocess, "run", boom)
    assert extract_palette(tmp_path / "v.mp4") is None


def test_extract_palette_none_when_all_samples_fail(tmp_path, monkeypatch):
    samples = [b""] * 5  # decode produced nothing for any frame
    _fake_ffmpeg(monkeypatch, samples)
    assert extract_palette(tmp_path / "v.mp4") is None


def test_props_default_palette_when_none_given(tmp_path):
    folder = _song_folder(tmp_path)
    props = _props_for(folder / "Song - Artist.json", "Song", "Artist", "x.mp3")
    assert props["palette"] == DEFAULT_PALETTE


def test_render_falls_back_to_default_palette(tmp_path, monkeypatch):
    # No source video at all (lyrics layout) -> designed fallback palette.
    folder = _song_folder(tmp_path)
    _mock_cli(tmp_path, monkeypatch)
    render_lyric_video(folder)
    assert _FakeProc.last_props["palette"] == DEFAULT_PALETTE


def test_render_lyrics_layout_uses_video_for_color_only(tmp_path, monkeypatch):
    folder = _song_folder(tmp_path)
    (tmp_path / "Song - Artist.video.mp4").write_bytes(b"v")
    _mock_cli(tmp_path, monkeypatch)
    seen = []

    def fake_extract(path):
        seen.append(path)
        return ["#112233", "#445566"]

    monkeypatch.setattr(video, "extract_palette", fake_extract)
    render_lyric_video(folder)
    assert seen == [tmp_path / "Song - Artist.video.mp4"]
    assert _FakeProc.last_props["palette"] == ["#112233", "#445566"]
    assert "videoFile" not in _FakeProc.last_props  # color only, no panel


def test_render_panel_passes_extracted_palette(tmp_path, monkeypatch):
    folder = _song_folder(tmp_path)
    (tmp_path / "Song - Artist.video.mp4").write_bytes(b"v")
    _mock_cli(tmp_path, monkeypatch)
    monkeypatch.setattr(video, "extract_palette", lambda p: ["#112233"])
    render_lyric_video(folder, layout="panel")
    assert _FakeProc.last_props["palette"] == ["#112233"]
    assert _FakeProc.last_props["videoFile"] == "Song - Artist.video.mp4"
