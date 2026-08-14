# YouTube Audio & Timestamped Lyrics Pipeline — Task Plan

Phased, dependency-ordered tasks derived from `PRD.md`. Tasks are intentionally **high-level**.
When you start a task, expand it into concrete sub-tasks — do not pre-expand everything.

**How to use:** Work top to bottom. Each task links to the PRD requirement IDs it implements;
those requirements' acceptance criteria (PRD §8/§9) are the Definition of Done. Check the box when
the acceptance criteria pass.

> Phases are agent-sized (well under ~30–50 requirements each). Build M1 fully before M2.

---

## Milestone 1 — Synced-lyrics happy path (Streamlit)
*Exit criteria: Paste URL → confirm metadata → when synced lyrics exist, get a 320 kbps MP3 + 4 timestamped lyric files in a "Title - Artist" folder; re-runs don't overwrite.*

- [x] **Project scaffold & launcher** — Python venv, pinned deps (yt-dlp, ffmpeg, streamlit, syncedlyrics), Streamlit skeleton, double-click `.bat` launcher · implements NFR-002, NFR-004 · DoD: PRD §10–11
  - Done 2026-06-10: `.venv` (Py 3.12.10) + `requirements.txt` (streamlit 1.58.0, syncedlyrics 1.0.1, yt-dlp ≥2026.6.9 floor for NFR-007); ffmpeg 8.0.1 confirmed on PATH; `app.py` skeleton verified serving (HTTP 200, localhost-only, telemetry off via `.streamlit/config.toml`); `Launch Lyrics Pipeline.bat` + `Update yt-dlp.bat`.
- [x] **URL input + start run** — single-screen Streamlit: URL field + Go · implements FR-001 · DoD: PRD §8
- [x] **Download audio + read metadata** — yt-dlp (bestaudio, title/artist/duration) · implements FR-003 · DoD: PRD §8
- [x] **Transcode to 320 kbps MP3** — ffmpeg · implements FR-004 · DoD: PRD §8
- [x] **Metadata confirm/edit step (always pause)** — show editable Title/Artist before lookup · implements FR-015 · DoD: PRD §8
- [x] **Multi-source synced-lyrics search** — `syncedlyrics` (LRCLIB + others) using confirmed metadata; allow reject/re-search · implements FR-005 · DoD: PRD §8
- [x] **Write 4 lyric formats** — `.txt` `[mm:ss]`, `.srt`, `.lrc`, `.json`, line-level (derive end times) · implements FR-007 · DoD: PRD §7–8
- [x] **Per-song output folder + naming** — "Title - Artist" subfolder; MP3 + lyrics share base name · implements FR-009 · DoD: PRD §8
- [x] **Re-run safety** — detect collision, warn, write versioned files (no silent overwrite) · implements FR-012 · DoD: PRD §8
- [x] **Per-stage progress/status** — show active stage in UI · implements FR-010 · DoD: PRD §8
- [x] **Run logging / instrumentation** — record lyrics source, processing time, success/failure · supports PRD §3, §10

> **M1 verified 2026-06-10.** `app.py` state machine (input → confirm pause → review → done) over the `pipeline/` package. Evidence: 34 offline tests (`pytest tests`, incl. Streamlit AppTest renders of all four states) + live smoke (`scripts/smoke_m1.py`): real download, ffprobe-confirmed 320 kbps, 58 synced lines via LRCLIB, all 5 files in a clean "Title - Artist" folder, collision versioned to "(2)". "Skip → transcribe" button present but disabled until M2.

## Milestone 2 — Transcription fallback (quality stack)
*Exit criteria: songs without synced lyrics get locally-transcribed line-level lyrics; audio preserved on lyrics failure; non-English warns & stops.*

- [x] **Vocal isolation (Demucs)** — isolate vocals before transcription on the fallback path · implements FR-006 (part) · DoD: PRD §8
- [x] **WhisperX transcription + alignment** — large-v3, CPU/int8, VAD + forced alignment → line-level timestamps; mark output as machine-transcribed · implements FR-006, FR-016 · DoD: PRD §8
- [x] **Non-English detect → warn & stop** — language check; skip the song without producing wrong-language lyrics · implements FR-014 · DoD: PRD §8
- [x] **Lyrics-source indicator** — state online vs transcribed in results · implements FR-008 · DoD: PRD §8
- [x] **Partial-failure isolation** — keep the MP3 and report clearly if lyrics can't be produced · implements FR-011 · DoD: PRD §8

> **M2 verified 2026-06-10.** `pipeline/transcribe.py` + `transcribe_worker.py`: Demucs and WhisperX each run in a child process (RAM freed between stages, NFR-006). Live evidence (`scripts/smoke_m2.py`, 95s clips): large-v3 first line 18.76s vs 18.9s synced reference; FR-016 held via a vocals-stem energy gate (drops Whisper silence-hallucinations VAD misses, e.g. "Thank you." at 9.8s in the instrumental intro — unit-tested); FR-014 gate fired on Despacito in 44s (detected `pt` — Whisper's es/pt sibling confusion, still a correct non-English stop) before paying transcription cost. `soundfile` added: torchaudio's only wav-save backend on Windows (Demucs output failed without it). Line-merging fixed same day: lines are rebuilt from word-level alignment (hard split at breath gaps ≥0.8s / sentence punctuation; lines >45 chars split recursively at their largest internal word gap). Same clip: 6 blob-lines → 29 lyric lines, all ≤60 chars (smoke-enforced). Residual quirk: short function words ("I", "of") occasionally land on a neighboring line — wav2vec2 alignment imprecision on short sung words; text-level touch-up, accepted. Perf finding: large-v3 int8 transcribes ≈1.2× realtime on the 4800H (117s for a 95s clip; earlier 1050s figure was dominated by the one-time 3 GB model download).

## Milestone 3 — Polish
*Exit criteria: URL validation, lyrics preview + open-folder, choosable output folder, quality/perf tuning.*

- [x] **URL validation + clear errors** — reject non-YouTube/malformed URLs, no partial files · implements FR-002 · DoD: PRD §8
- [x] **Choosable output folder** — view/change the output root · implements FR-013 · DoD: PRD §8
- [x] **Results panel** — lyrics preview + "open folder" button · implements FR-018 · DoD: PRD §8
- [x] **Quality/perf tuning** — meet NFR-001/008 targets; optional fast mode (R-001) · DoD: PRD §9

> **M3 implemented 2026-06-10.** FR-002: `download.validate_url` rejects non-YouTube/malformed/playlist URLs *before* any work dir or network call (21 cases unit-tested; an AppTest click-through asserts the readable error and zero side effects). FR-013: a Settings expander on the input screen exposes a per-session output root; an uncreatable path falls back to the default `Output/` with a warning instead of losing the run (FR-011 spirit). FR-018: the done screen adds a lyrics preview and an "Open output folder" button. Quality/perf: a fast-transcription checkbox runs WhisperX **`medium` — deliberately multilingual, not the `medium.en` this task once suggested** — the FR-014 language gate detects on the loaded model and English-only `.en` models can't detect; default remains large-v3 (NFR-010). Perf context: large-v3 int8 ≈1.2× realtime (M2 evidence), so a 4-min song transcribes in ≈6–7 min; fast mode brings the slow path inside the NFR-001 ≤5-min soft target. Same-day quality work beyond this list: FR-005 lookup hardened against wrong-song matches (LRCLIB structured search, title variants, duration ranking — R-006) and `pipeline/correct.py` auto-corrects transcriptions against online lyrics (R-004): `synced_aligned` adopts online text+timing shifted onto this audio (live Akon evidence: constant +56.8s offset, 24 anchor lines, all mishearings fixed), else `plain_corrected` patches misheard words keeping WhisperX timing, else the raw transcription is kept. The M2 "merged lines / stray short words" quirk is largely superseded by the corrector. 96 offline tests pass.

---

## Milestone 4 — Lyric video rendering (scope extension, user-approved 2026-06-10)
*PRD §4 lists video rendering as a non-goal; the user explicitly overrode that on 2026-06-10 after approving a rendered demo. Decisions: app button + CLI, 1920×1080@30, MP4 lands in the song's folder.*

- [x] **Props-driven Remotion composition** — `video/` project (dark-gradient karaoke look: title card over the intro, line-by-line lyrics with dimmed next-line preview, progress bar); per-song data via input props + `calculateMetadata`; `node_modules` is a junction to the vendored install in `..\Video Production\vendor\remotion`.
- [x] **Render driver** — `pipeline/video.py`: picks the newest MP3+`.json` pair in a song folder (versioned bases win), parses Title/Artist from the FR-009 base name, passes the song folder as Remotion's public dir, writes `<base>.mp4` with never-overwrite versioning (FR-012 spirit).
- [x] **CLI** — `scripts/render_video.py "Output\<Title - Artist>"`; no args lists renderable folders.
- [x] **App button** — done screen offers "🎬 Render lyric video" when the run produced lyrics; streams Remotion progress; a render failure never touches the song's other files (FR-011 spirit).
- [x] **Tests + smoke** — 12 offline unit tests (`tests/test_video.py`) + AppTest button checks; `scripts/smoke_video.py` does a real 4s 1080p render (~12s) and ffprobe-verifies h264/1920×1080/aac.

> **M4 evidence 2026-06-10.** Smoke render PASS (12s, h264 1920×1080 + aac). Full-song render verified on the Akon folder. One real bug caught and regression-tested during verification: a *relative* song-folder path made `--public-dir` resolve against the CLI's `cwd` (`video/`), Remotion silently treated the missing dir as empty, and the audio 404'd mid-render — the driver now resolves all paths absolute. Operational notes: `remotion render` without arguments starts a default render instead of printing help (always pass explicit args); Remotion's one-time Chrome Headless Shell (~113 MB) lives in the vendored `node_modules\.remotion`.

## Milestone 5 — Video + lyrics panel layout (scope extension, user-approved 2026-06-10)
*Extends M4's override of PRD §4: the user also approved downloading the visual stream. Design spec: `docs/superpowers/specs/2026-06-10-video-panel-layout-design.md`. Decisions: second render option (lyrics-only stays), Spotify-style scrolling panel (line-level only), video fetched on every run (non-fatal), all-in-Remotion via muted `OffthreadVideo` + the pipeline MP3 as the only audio track.*

- [x] **Stage-1 video download** — `download.download_video`: video-only stream, ≤1080p, MP4/h264 preferred; failure warns and the run continues (FR-011 spirit). `outputs.place_video` keeps it as `<base>.video.<ext>` in the song folder; a stray `.video.*` versions the base like any output (FR-012).
- [x] **`VideoPanel` composition** — `video/src/VideoPanel.tsx`: music video letterboxed on the left 1440px over the M4 gradient, 480px lyrics tab on the right (title/artist header, spring-scrolled line list centered on the active line, edge fades), full-width progress bar; registered beside `LyricVideo` in `Root.tsx`.
- [x] **Render driver + rescue** — `render_lyric_video(layout="panel")` renders `<base> [video+lyrics].mp4` (never-overwrite); `find_video_file` picks the newest base-matched source; `fetch_video` recovers the URL from `logs/runs.jsonl` (sanitized title/artist match) to rescue pre-M5 folders.
- [x] **App button + CLI** — done screen offers "🎬 Render video + lyrics panel" beside the M4 button (fetches the video first when missing; disabled with a hint when unrecoverable); `scripts/render_video.py --layout panel`; the no-arg listing notes video availability.
- [x] **Tests + smoke** — suite grown to 125 offline tests (driver, outputs, download options, run-log lookup, AppTest button states); `scripts/smoke_video.py` renders both layouts (panel against an ffmpeg test-pattern clip, no extra network).

## Cross-cutting (apply throughout)

- [ ] Meet non-functional requirements NFR-001 … NFR-010 (PRD §9) — note **NFR-010 quality > speed** governs tradeoffs.
- [ ] Honor all non-goals (PRD §4) — do not add unrequested scope (no batch, line-level only, English-only). *Exception: the no-video-rendering and no-visual-stream-download non-goals were consciously overridden by the user — see M4/M5.*
- [ ] Tests cover the acceptance criteria for every P0/P1 requirement.
- [ ] Keep the only network calls to the YouTube download + lyrics lookup; transcription stays local (NFR-005).

## Traceability

| Requirement | Milestone | Task |
| ----------- | --------- | ---- |
| FR-001 | M1 | URL input + start run |
| FR-003 | M1 | Download audio + read metadata |
| FR-004 | M1 | Transcode to 320 kbps MP3 |
| FR-005 | M1 | Multi-source synced-lyrics search |
| FR-007 | M1 | Write 4 lyric formats |
| FR-009 | M1 | Per-song output folder + naming |
| FR-010 | M1 | Per-stage progress/status |
| FR-012 | M1 | Re-run safety |
| FR-015 | M1 | Metadata confirm/edit step |
| FR-006 | M2 | Vocal isolation + WhisperX transcription |
| FR-008 | M2 | Lyrics-source indicator |
| FR-011 | M2 | Partial-failure isolation |
| FR-014 | M2 | Non-English detect → warn & stop |
| FR-016 | M2 | WhisperX VAD (no hallucinated lines) |
| FR-002 | M3 | URL validation + clear errors |
| FR-013 | M3 | Choosable output folder |
| FR-018 | M3 | Results panel (preview + open folder) |
| NFR-001…010 | All | Cross-cutting |
