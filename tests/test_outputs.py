"""Output naming + collision safety — FR-009, FR-012."""

from pipeline.outputs import place_video, plan_output, sanitize_name


def test_sanitize_strips_windows_invalid_chars():
    assert sanitize_name('A<B>C:D"E/F\\G|H?I*J') == "ABCDEFGHIJ"


def test_sanitize_collapses_whitespace_and_trailing_dots():
    assert sanitize_name("  Song   Name... ") == "Song Name"


def test_sanitize_empty_becomes_untitled():
    assert sanitize_name('???') == "Untitled"


def test_fresh_run_uses_plain_base(tmp_path):
    plan = plan_output(tmp_path, "Song", "Artist")
    assert plan.folder == tmp_path / "Song - Artist"
    assert plan.base == "Song - Artist"
    assert plan.versioned is False


def test_rerun_collision_versions_to_2(tmp_path):
    folder = tmp_path / "Song - Artist"
    folder.mkdir()
    (folder / "Song - Artist.mp3").touch()
    plan = plan_output(tmp_path, "Song", "Artist")
    assert plan.base == "Song - Artist (2)"
    assert plan.versioned is True


def test_third_run_versions_to_3(tmp_path):
    folder = tmp_path / "Song - Artist"
    folder.mkdir()
    (folder / "Song - Artist.mp3").touch()
    (folder / "Song - Artist (2).mp3").touch()
    plan = plan_output(tmp_path, "Song", "Artist")
    assert plan.base == "Song - Artist (3)"


def test_existing_empty_folder_not_versioned(tmp_path):
    (tmp_path / "Song - Artist").mkdir()
    plan = plan_output(tmp_path, "Song", "Artist")
    assert plan.base == "Song - Artist"
    assert plan.versioned is False


def test_place_video_uses_video_infix_and_keeps_ext(tmp_path):
    # M5: `<base>.video.<ext>` can never collide with rendered `<base>*.mp4`.
    plan = plan_output(tmp_path, "Song", "Artist")
    work = tmp_path / "work"
    work.mkdir()
    src = work / "source_video.webm"
    src.write_bytes(b"v")
    dest = place_video(plan, src)
    assert dest == tmp_path / "Song - Artist" / "Song - Artist.video.webm"
    assert dest.read_bytes() == b"v" and not src.exists()


def test_stray_source_video_versions_base(tmp_path):
    # M5 + FR-012: a leftover source video alone must still version the base.
    folder = tmp_path / "Song - Artist"
    folder.mkdir()
    (folder / "Song - Artist.video.mp4").touch()
    plan = plan_output(tmp_path, "Song", "Artist")
    assert plan.base == "Song - Artist (2)"
    assert plan.versioned is True
