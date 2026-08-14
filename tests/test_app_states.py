"""Offline render checks for the four UI states (FR-001/002/010/013/015/018).

Uses Streamlit's AppTest: seeds session_state, renders, asserts — no network,
no clicks that would trigger downloads or lyrics lookups. (Clicking Go with an
invalid URL is safe: FR-002 rejects before any work happens.)
"""

from streamlit.testing.v1 import AppTest

APP = "app.py"


def _at(stage=None, run=None):
    at = AppTest.from_file(APP, default_timeout=30)
    if stage is not None:
        at.session_state["stage"] = stage
        at.session_state["run"] = run or {}
    return at.run()


def test_input_state_has_url_field_and_go():
    at = _at()
    assert not at.exception
    assert at.text_input[0].placeholder.startswith("https://www.youtube.com")
    assert at.button[0].label == "Go"
    assert at.button[0].disabled  # empty URL → Go disabled (FR-001 guard)


def test_input_rejects_invalid_url_without_side_effects():
    # FR-002: a clear error, and no work dir / downloads ever started.
    at = _at()
    at.text_input[0].set_value("https://vimeo.com/123456")
    at.button[0].click()
    at.run()
    assert not at.exception
    assert len(at.error) == 1
    assert "Invalid URL" in at.error[0].value


def test_input_settings_expose_output_root():
    # FR-013: output location visible and changeable.
    at = _at()
    assert not at.exception
    out_root = at.text_input(key="out_root")
    assert out_root.value.endswith("Output")


def test_confirm_state_shows_editable_metadata():
    at = _at(
        "confirm",
        {"title": "Song", "artist": "Artist", "duration": 228.0},
    )
    assert not at.exception
    values = [ti.value for ti in at.text_input]
    assert "Song" in values and "Artist" in values
    labels = [b.label for b in at.button]
    assert "Look up lyrics" in labels
    assert "Skip → transcribe" in labels
    assert at.button(key="skip_transcribe").disabled is False  # M2: enabled
    assert at.checkbox(key="fast_mode").value is False  # quality default (NFR-010)


def test_confirm_miss_offers_transcribe_and_mp3_only():
    at = _at(
        "confirm",
        {"title": "Song", "artist": "Artist", "duration": 228.0, "miss": True},
    )
    assert not at.exception
    assert len(at.warning) == 1
    assert at.button(key="transcribe_miss").label == "Transcribe locally (slow)"
    assert at.button(key="finish_mp3").label == "Finish with MP3 only"


def test_review_state_previews_lyrics_with_accept_reject():
    at = _at(
        "review",
        {"title": "Song", "artist": "Artist", "duration": 228.0,
         "lrc": "[00:12]First line\n[00:17]Second line"},
    )
    assert not at.exception
    assert "[00:12] First line" in at.code[0].value
    labels = [b.label for b in at.button]
    assert "Use these lyrics" in labels
    assert "Wrong version — search again" in labels


def test_done_state_lists_outputs():
    at = _at(
        "done",
        {"result": {
            "base": "Song - Artist",
            "folder": "C:/x/Output/Song - Artist",
            "files": {"mp3": "C:/x/Output/Song - Artist/Song - Artist.mp3"},
            "versioned": False,
            "lyrics_source": "online synced-lyrics search",
        }},
    )
    assert not at.exception
    assert any("New song" == b.label for b in at.button)


def test_done_results_panel_has_preview_and_open_folder():
    # FR-018: lyrics preview + an "open folder" action.
    at = _at(
        "done",
        {"result": {
            "base": "Song - Artist",
            "folder": "C:/x/Output/Song - Artist",
            "files": {"mp3": "C:/x/Output/Song - Artist/Song - Artist.mp3"},
            "versioned": False,
            "lyrics_source": "online synced-lyrics search",
            "preview": "[00:12] First line\n[00:17] Second line",
        }},
    )
    assert not at.exception
    assert "[00:12] First line" in at.code[0].value
    assert at.button(key="open_folder").label == "Open output folder"


def test_done_mp3_only_run_has_no_preview_block():
    at = _at(
        "done",
        {"result": {
            "base": "Song - Artist",
            "folder": "C:/x/Output/Song - Artist",
            "files": {"mp3": "C:/x/Output/Song - Artist/Song - Artist.mp3"},
            "versioned": False,
            "lyrics_source": "none — finished with MP3 only",
            "preview": None,
        }},
    )
    assert not at.exception
    assert len(at.code) == 0
    # M4: no lyrics → no lyric-video render offer either.
    assert not any("Render lyric video" in b.label for b in at.button)


def test_done_with_lyrics_offers_video_render():
    # M4 scope extension: completed runs with lyrics can render a lyric video.
    at = _at(
        "done",
        {"result": {
            "base": "Song - Artist",
            "folder": "C:/x/Output/Song - Artist",
            "files": {
                "mp3": "C:/x/Output/Song - Artist/Song - Artist.mp3",
                "json": "C:/x/Output/Song - Artist/Song - Artist.json",
            },
            "versioned": False,
            "lyrics_source": "online synced-lyrics search",
            "preview": "[00:12] First line",
        }},
    )
    assert not at.exception
    assert at.button(key="render_video").label.startswith("🎬 Render lyric video")


def test_done_panel_button_enabled_when_video_on_disk():
    # M5: with the source video saved, the panel render is offered directly.
    at = _at(
        "done",
        {"result": {
            "base": "Song - Artist",
            "folder": "C:/x/Output/Song - Artist",
            "files": {
                "mp3": "C:/x/Output/Song - Artist/Song - Artist.mp3",
                "json": "C:/x/Output/Song - Artist/Song - Artist.json",
                "video": "C:/x/Output/Song - Artist/Song - Artist.video.mp4",
            },
            "versioned": False,
            "lyrics_source": "online synced-lyrics search",
            "preview": "[00:12] First line",
        }},
    )
    assert not at.exception
    btn = at.button(key="render_panel")
    assert btn.label == "🎬 Render video + lyrics panel"
    assert btn.disabled is False


def test_done_panel_button_fetch_mode_without_video():
    # M5: no source video and no run-log URL → fetch-labelled but disabled.
    # The base is deliberately one no real run log can contain.
    at = _at(
        "done",
        {"result": {
            "base": "ZZZ Apptest Song - Nobody Ever",
            "folder": "C:/x/Output/ZZZ Apptest Song - Nobody Ever",
            "files": {
                "mp3": "C:/x/m.mp3",
                "json": "C:/x/m.json",
            },
            "versioned": False,
            "lyrics_source": "online synced-lyrics search",
            "preview": "[00:12] First line",
        }},
    )
    assert not at.exception
    btn = at.button(key="render_panel")
    assert "(fetches video first)" in btn.label
    assert btn.disabled is True


def test_done_state_warns_when_versioned():
    at = _at(
        "done",
        {"result": {
            "base": "Song - Artist (2)",
            "folder": "C:/x/Output/Song - Artist",
            "files": {},
            "versioned": True,
            "lyrics_source": "online synced-lyrics search",
        }},
    )
    assert not at.exception
    assert len(at.warning) == 1  # FR-012: collision must surface a warning


def _done_result(kind, label, detail=None):
    return {"result": {
        "base": "Song - Artist", "folder": "C:/x/Output/Song - Artist",
        "files": {"mp3": "C:/x/Output/Song - Artist/Song - Artist.mp3"},
        "versioned": False, "lyrics_source": label,
        "source_kind": kind, "detail": detail,
    }}


def test_done_transcribed_source_stated_plainly():
    # FR-008: machine-transcribed runs state their source without alarm styling.
    at = _at("done", _done_result("transcribed", "machine-transcribed locally"))
    assert not at.exception
    assert len(at.warning) == 0 and len(at.error) == 0


def test_done_corrected_kinds_render_plainly():
    # FR-008: auto-corrected outcomes state their source without alarm styling.
    for kind, label in (
        ("synced_aligned", "online synced lyrics, auto-aligned (+56.7s)"),
        ("transcribed_corrected", "machine-transcribed, auto-corrected (4 lines)"),
    ):
        at = _at("done", _done_result(kind, label))
        assert not at.exception
        assert len(at.warning) == 0 and len(at.error) == 0


def test_done_non_english_shows_warning():
    # FR-014: non-English stop is surfaced as a warning; MP3 still listed.
    at = _at("done", _done_result("non_english", "skipped — non-English (es)", "es"))
    assert not at.exception
    assert len(at.warning) == 1


def test_done_failed_lyrics_shows_error_and_keeps_mp3():
    # FR-011: lyrics failure is an error, but the MP3 file is still in the list.
    at = _at("done", _done_result("failed", "lyrics could not be produced", "boom"))
    assert not at.exception
    assert len(at.error) == 1
