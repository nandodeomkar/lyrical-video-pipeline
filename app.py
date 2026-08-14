"""YouTube Audio & Timestamped Lyrics Pipeline — single-screen Streamlit UI.

State machine over st.session_state, mirroring PRD §7's screen states:
  input   — URL + Go (FR-001); Go runs download (FR-003) and transcode
            (FR-004) with per-stage status (FR-010).
  confirm — mandatory metadata pause: editable Title/Artist (FR-015); the
            synced-lyrics lookup (FR-005) uses the confirmed values.
  review  — show the matched lyrics; accept, or reject and re-search (FR-005).
  done    — outputs written (FR-007, FR-009, FR-012); summary + reset.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import streamlit as st

from pipeline.correct import auto_correct
from pipeline.download import download_audio, download_video, validate_url
from pipeline.formats import write_all
from pipeline.lyrics import LyricLine, parse_lrc, search_synced
from pipeline.outputs import place_mp3, place_video, plan_output
from pipeline.runlog import append_run
from pipeline.transcode import transcode_to_mp3
from pipeline.transcribe import NonEnglishError, isolate_vocals, transcribe_aligned
from pipeline.video import fetch_video, find_run_url, render_lyric_video

ROOT = Path(__file__).parent
OUT_ROOT = ROOT / "Output"  # default; changeable per session in Settings (FR-013)
WORK_ROOT = ROOT / "work"
LOG_DIR = ROOT / "logs"

FAST_MODEL = "medium"  # multilingual on purpose: the FR-014 language gate
# detects on the loaded model, and English-only ".en" models can't detect.

PREVIEW_LINES = 12

st.set_page_config(page_title="Lyrics Pipeline", page_icon="🎵", layout="centered")
st.title("YouTube Audio & Timestamped Lyrics Pipeline")
st.caption(
    "One English-language YouTube music-video URL in → 320 kbps MP3 + "
    "line-timestamped lyrics (.txt / .srt / .lrc / .json) out."
)

if "stage" not in st.session_state:
    st.session_state.stage = "input"
    st.session_state.run = {}


def _fmt_mmss(t: float) -> str:
    m, s = divmod(int(round(t)), 60)
    return f"{m:02d}:{s:02d}"


def _reset() -> None:
    run = st.session_state.run
    if (wd := run.get("work_dir")) and Path(wd).exists():
        shutil.rmtree(wd, ignore_errors=True)
    st.session_state.stage = "input"
    st.session_state.run = {}


def _finish(
    run: dict,
    title: str,
    artist: str,
    lines: list[LyricLine] | None,
    source: str,  # "synced" | "synced_aligned" | "transcribed" | "transcribed_corrected" | "none" | "non_english" | "failed"
    detail: str | None = None,
) -> None:
    """Write outputs (FR-007/009/012), log the run, and move to the done state.

    The MP3 is always placed, whatever happened to lyrics (FR-011).
    """
    t0 = time.perf_counter()
    out_root = Path(st.session_state.get("out_root") or OUT_ROOT)
    out_root_fallback = False
    try:
        out_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        # A bad Settings path must never lose a finished run (FR-011 spirit).
        out_root, out_root_fallback = OUT_ROOT, True
    plan = plan_output(out_root, title, artist)
    mp3_path = place_mp3(plan, Path(run["mp3_work"]))
    files: dict[str, Path] = {"mp3": mp3_path}
    # M5: keep the source video for the optional panel render; losing it must
    # never lose the run (FR-011 spirit).
    if (vw := run.get("video_work")) and Path(vw).exists():
        try:
            files["video"] = place_video(plan, Path(vw))
        except OSError:
            pass
    if lines:
        files |= write_all(lines, run["duration"], plan.folder, plan.base)
    shutil.rmtree(run["work_dir"], ignore_errors=True)

    stage_seconds = {
        "download": round(run["t_download"], 1),
        "transcode": round(run["t_transcode"], 1),
        "video_download": round(run.get("t_video", 0.0), 1),
        "lyrics_search": round(run.get("t_lyrics", 0.0), 1),
        "vocal_isolation": round(run.get("t_demucs", 0.0), 1),
        "transcription": round(run.get("t_whisperx", 0.0), 1),
        "lyrics_correction": round(run.get("t_correct", 0.0), 1),
        "write": round(time.perf_counter() - t0, 1),
    }
    # Active processing only — excludes time parked at the confirm pause.
    stage_seconds["total"] = round(sum(stage_seconds.values()), 1)
    append_run(
        LOG_DIR,
        {
            "url": run["url"],
            "title": title,
            "artist": artist,
            "lyrics_source": source if lines else "none",
            "lyrics_outcome": source,
            "detail": detail,
            "mp3_saved": True,
            "video_saved": "video" in files,
            "lyrics_saved": bool(lines),
            "versioned": plan.versioned,
            "seconds": stage_seconds,
            "success": True,
        },
    )
    if source == "synced":
        label = "online synced-lyrics search"
    elif source == "synced_aligned":
        label = f"online synced lyrics, auto-aligned to this audio ({detail}) — verified against the local transcription"
    elif source == "transcribed_corrected":
        label = f"machine-transcribed locally, auto-corrected against online lyrics ({detail}) — spot-check timing"
    elif source == "transcribed":
        label = "machine-transcribed locally (Demucs + WhisperX large-v3) — spot-check timing"
    elif source == "non_english":
        label = f"skipped — detected non-English vocals ({detail}); English-only scope"
    elif source == "failed":
        label = "lyrics could not be produced — the MP3 was kept"
    else:
        label = "none — finished with MP3 only (no synced match accepted)"
    preview = None
    if lines:
        preview = "\n".join(f"[{_fmt_mmss(ln.start)}] {ln.text}" for ln in lines[:PREVIEW_LINES])
        if len(lines) > PREVIEW_LINES:
            preview += f"\n… {len(lines) - PREVIEW_LINES} more lines"
    run["result"] = {
        "base": plan.base,
        "folder": str(plan.folder),
        "files": {ext: str(p) for ext, p in files.items()},
        "versioned": plan.versioned,
        "lyrics_source": label,
        "source_kind": source,
        "detail": detail,
        "preview": preview,
        "out_root_fallback": out_root_fallback,
    }
    st.session_state.stage = "done"
    st.rerun()


def _run_transcription(run: dict, title: str, artist: str) -> None:
    """Slow path (FR-006): Demucs → WhisperX, with the FR-014 language gate."""
    run["title"], run["artist"] = title, artist
    fast = bool(st.session_state.get("fast_mode"))
    model = FAST_MODEL if fast else None  # None → transcribe.py default (large-v3)
    try:
        with st.status(
            "Transcribing locally — fast mode (Whisper medium)…"
            if fast
            else "Transcribing locally — slow path, quality first (~10–30 min on CPU)…",
            expanded=True,
        ) as status:
            st.write("🎤 Isolating vocals (Demucs)…")
            t0 = time.perf_counter()
            vocals = isolate_vocals(Path(run["mp3_work"]), Path(run["work_dir"]))
            run["t_demucs"] = time.perf_counter() - t0
            st.write(f"✔ Vocals isolated ({run['t_demucs']:.0f}s)")
            st.write(
                f"📝 Transcribing + aligning (WhisperX {model or 'large-v3'}, CPU/int8, VAD)…"
            )
            t1 = time.perf_counter()
            lines = (
                transcribe_aligned(vocals, Path(run["work_dir"]), model=model)
                if model
                else transcribe_aligned(vocals, Path(run["work_dir"]))
            )
            run["t_whisperx"] = time.perf_counter() - t1
            st.write(f"✔ {len(lines)} lines transcribed and aligned")
            st.write("🔎 Checking the transcription against online lyrics…")
            t2 = time.perf_counter()
            corr = auto_correct(lines, title, artist, run["duration"])
            run["t_correct"] = time.perf_counter() - t2
            if corr.method == "synced_aligned":
                st.write(
                    f"✔ Matched online synced lyrics — adopted them shifted "
                    f"{corr.offset:+.1f}s ({corr.anchors} anchor lines agree)"
                )
            elif corr.method == "plain_corrected":
                st.write(f"✔ Corrected {corr.replaced} misheard line(s) from online lyrics")
            else:
                st.write("• No online lyrics matched this audio — keeping the raw transcription")
            status.update(label="Transcription complete", state="complete")
        if corr.method == "synced_aligned":
            _finish(run, title, artist, corr.lines, "synced_aligned",
                    detail=f"offset {corr.offset:+.1f}s, {corr.anchors} anchors")
        elif corr.method == "plain_corrected":
            _finish(run, title, artist, corr.lines, "transcribed_corrected",
                    detail=f"{corr.replaced} lines corrected, {corr.anchors} matched")
        else:
            _finish(run, title, artist, lines, "transcribed")
    except NonEnglishError as exc:
        _finish(run, title, artist, None, "non_english", detail=exc.language)
    except Exception as exc:
        _finish(run, title, artist, None, "failed", detail=str(exc)[:800])


stage = st.session_state.stage
run = st.session_state.run

if stage == "input":
    url = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...")
    with st.expander("⚙ Settings"):
        st.text_input(
            "Output folder",
            value=st.session_state.get("out_root", str(OUT_ROOT)),
            key="out_root",
            help="Per-song folders are created inside this root (FR-013).",
        )
    go = st.button("Go", type="primary", disabled=not url.strip())
    if go and (problem := validate_url(url)):
        # FR-002: reject before any directory or network work — no files created.
        st.error(f"Invalid URL — {problem}")
    elif go:
        work_dir = WORK_ROOT / time.strftime("%Y%m%d-%H%M%S")
        try:
            with st.status("Processing…", expanded=True) as status:
                st.write("⏬ Downloading audio…")
                t0 = time.perf_counter()
                dl = download_audio(url.strip(), work_dir)
                t1 = time.perf_counter()
                st.write(f"✔ Downloaded audio ({_fmt_mmss(dl.duration)})")
                st.write("🎚 Transcoding to 320 kbps MP3…")
                mp3 = transcode_to_mp3(dl.audio_path, work_dir / "song.mp3")
                t2 = time.perf_counter()
                st.write("✔ Saved MP3 (320 kbps)")
                # M5: fetch the video stream for the optional panel render.
                # Non-fatal — the MP3 + lyrics never depend on it (FR-011 spirit).
                st.write("📺 Downloading video (for the optional video + lyrics render)…")
                try:
                    video_work = str(download_video(url.strip(), work_dir))
                    st.write("✔ Video saved (≤1080p)")
                except Exception as vexc:
                    video_work = None
                    st.write(f"⚠ Video download failed — continuing without it ({str(vexc)[:120]})")
                t3 = time.perf_counter()
                status.update(label="Audio ready — confirm song details", state="complete")
            run.update(
                url=url.strip(),
                work_dir=str(work_dir),
                mp3_work=str(mp3),
                video_work=video_work,
                title=dl.title,
                artist=dl.artist,
                duration=dl.duration,
                t_download=t1 - t0,
                t_transcode=t2 - t1,
                t_video=t3 - t2,
            )
            st.session_state.stage = "confirm"
            st.rerun()
        except Exception as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            append_run(
                LOG_DIR,
                {"url": url.strip(), "success": False, "failed_stage": "download/transcode", "error": str(exc)[:500]},
            )
            st.error(f"Download/transcode failed: {exc}")

elif stage == "confirm":
    st.success(f"Audio ready ({_fmt_mmss(run['duration'])}) — MP3 saved at 320 kbps.")
    st.subheader("Confirm song details")
    st.caption("Edit if the detected match looks wrong — the lyrics lookup uses these values.")
    title = st.text_input("Title", value=run["title"])
    artist = st.text_input("Artist", value=run["artist"])

    fields_ok = bool(title.strip() and artist.strip())
    col1, col2 = st.columns(2)
    look_up = col1.button("Look up lyrics", type="primary", key="lookup", disabled=not fields_ok)
    skip = col2.button(
        "Skip → transcribe",
        key="skip_transcribe",
        disabled=not fields_ok,
        help="Slow path: Demucs vocal isolation + WhisperX large-v3 on CPU (~10–30 min).",
    )
    st.checkbox(
        "Fast transcription (Whisper medium — quicker, slightly less accurate)",
        key="fast_mode",
        help="Default is large-v3: quality first (NFR-010). Fast mode trades a "
        "little accuracy for roughly 3× speed (R-001); the language gate and "
        "online auto-correction still apply.",
    )

    if run.get("miss"):
        st.warning(
            "No synced lyrics found for that title/artist. Edit the fields and retry, "
            "transcribe locally, or finish with the MP3 only."
        )
        mcol1, mcol2 = st.columns(2)
        if mcol1.button("Transcribe locally (slow)", key="transcribe_miss"):
            _run_transcription(run, title.strip(), artist.strip())
        if mcol2.button("Finish with MP3 only", key="finish_mp3"):
            _finish(run, title.strip(), artist.strip(), None, "none")

    if skip:
        _run_transcription(run, title.strip(), artist.strip())

    if look_up:
        run["title"], run["artist"] = title.strip(), artist.strip()
        with st.spinner("Searching synced lyrics (LRCLIB + other sources)…"):
            t0 = time.perf_counter()
            lrc = search_synced(run["title"], run["artist"], run["duration"])
            run["t_lyrics"] = run.get("t_lyrics", 0.0) + (time.perf_counter() - t0)
        if lrc and parse_lrc(lrc):
            run["lrc"] = lrc
            run["miss"] = False
            st.session_state.stage = "review"
        else:
            run["miss"] = True
        st.rerun()

elif stage == "review":
    st.subheader("Synced lyrics found")
    lines = parse_lrc(run["lrc"])
    preview = "\n".join(f"[{_fmt_mmss(ln.start)}] {ln.text}" for ln in lines[:PREVIEW_LINES])
    if len(lines) > PREVIEW_LINES:
        preview += f"\n… {len(lines) - PREVIEW_LINES} more lines"
    st.code(preview, language=None)
    st.caption(f"{len(lines)} timed lines · source: online synced-lyrics search")

    col1, col2 = st.columns(2)
    if col1.button("Use these lyrics", type="primary", key="accept"):
        _finish(run, run["title"], run["artist"], parse_lrc(run["lrc"]), "synced")
    if col2.button("Wrong version — search again", key="reject"):
        st.session_state.stage = "confirm"
        st.rerun()

elif stage == "done":
    res = run["result"]
    st.subheader(f'Done — "{res["base"]}"')
    if res["versioned"]:
        st.warning(
            "This song already had output files — new versioned files were written "
            "instead of overwriting the old ones."
        )
    kind = res.get("source_kind", "synced")
    if kind == "non_english":
        st.warning(f"**Lyrics source:** {res['lyrics_source']}")
    elif kind == "failed":
        st.error(f"**Lyrics source:** {res['lyrics_source']}")
        if res.get("detail"):
            st.caption(f"Error detail: {res['detail']}")
    else:
        st.write(f"**Lyrics source:** {res['lyrics_source']}")
    if res.get("out_root_fallback"):
        st.warning(
            "The output folder from Settings couldn't be created — "
            f"files were saved under the default `{OUT_ROOT}` instead."
        )
    st.write(f"**Folder:** `{res['folder']}`")
    st.write("**Files written:**")
    for ext in ("mp3", "txt", "srt", "lrc", "json", "video", "mp4", "panel_mp4"):
        if ext in res["files"]:
            st.write(f"- `{Path(res['files'][ext]).name}`")
    if res.get("preview"):
        st.write("**Lyrics preview:**")
        st.code(res["preview"], language=None)
    if res["files"].get("json"):
        # M4 scope extension: lyric video from this run's MP3 + timed lyrics.
        # M5: plus the original music video with a lyrics panel beside it.
        vcol1, vcol2 = st.columns(2)
        render_lyrics_only = vcol1.button("🎬 Render lyric video (~6–10 min)", key="render_video")
        need_fetch = "video" not in res["files"]
        can_fetch = (not need_fetch) or bool(find_run_url(LOG_DIR, res["base"]))
        panel_label = "🎬 Render video + lyrics panel" + (
            " (fetches video first)" if need_fetch else ""
        )
        render_panel = vcol2.button(
            panel_label,
            key="render_panel",
            disabled=not can_fetch,
            help=(
                "No source video and no URL in the run log — re-run the song once "
                "through the app to fetch its video."
            )
            if not can_fetch
            else None,
        )
        if render_lyrics_only:
            mp4 = None
            try:
                with st.status("Rendering lyric video (Remotion, 1080p30)…", expanded=True) as vstatus:
                    progress_line = st.empty()
                    mp4 = render_lyric_video(
                        Path(res["folder"]),
                        on_progress=lambda line: progress_line.text(line),
                    )
                    vstatus.update(label=f"Lyric video rendered — {mp4.name}", state="complete")
            except Exception as exc:
                st.error(f"Video render failed — the song's other files are untouched: {exc}")
            if mp4 is not None:
                res["files"]["mp4"] = str(mp4)
                st.rerun()
        if render_panel:
            mp4 = None
            try:
                with st.status(
                    "Rendering video + lyrics panel (Remotion, 1080p30)…", expanded=True
                ) as vstatus:
                    if need_fetch:
                        st.write("⏬ Fetching the music video (≤1080p)…")
                        res["files"]["video"] = str(fetch_video(Path(res["folder"])))
                        st.write("✔ Video fetched")
                    progress_line = st.empty()
                    mp4 = render_lyric_video(
                        Path(res["folder"]),
                        layout="panel",
                        on_progress=lambda line: progress_line.text(line),
                    )
                    vstatus.update(
                        label=f"Video + lyrics panel rendered — {mp4.name}", state="complete"
                    )
            except Exception as exc:
                st.error(f"Panel render failed — the song's other files are untouched: {exc}")
            if mp4 is not None:
                res["files"]["panel_mp4"] = str(mp4)
                st.rerun()
    col1, col2 = st.columns(2)
    if col1.button("Open output folder", key="open_folder"):
        os.startfile(res["folder"])  # FR-018: jump straight to the files
    if col2.button("New song", type="primary"):
        _reset()
        st.rerun()
