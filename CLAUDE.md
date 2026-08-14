# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status: M1–M6 implemented; PRD scope is feature-complete

Both lyrics paths work (verified live 2026-06-10): the synced happy path and the transcription fallback (Demucs → WhisperX large-v3, CPU/int8, FR-014 English gate, FR-016 energy gate). The FR-005 lookup is hardened against wrong-song matches (LRCLIB structured search first, title variants, duration ranking — R-006), and `pipeline/correct.py` auto-corrects transcriptions against online lyrics (R-004). M3 polish landed 2026-06-10 (see the M3 evidence note in TASKS.md): FR-002 URL validation before any side effects, FR-013 choosable output root (Settings expander, safe fallback), FR-018 results panel (lyrics preview + open-folder), and a fast-transcription mode (WhisperX `medium`, deliberately multilingual so the FR-014 gate keeps working; default stays large-v3 per NFR-010). `app.py` is a Streamlit session-state machine (input → confirm pause → review → done) driving the UI-agnostic `pipeline/` package. 96 offline tests pass; `scripts/smoke_m1.py` and `scripts/smoke_m2.py` verify both paths against real services. The repo is not under git. Remaining: cross-cutting checks in TASKS.md and any user-driven polish. Treat the PRD as the contract for what to build.

M4 (user-approved scope extension, 2026-06-10 — overrides the PRD §4 no-video-rendering non-goal): a production lyric-video render stage. `video/` holds the props-driven Remotion composition (1920×1080@30, dark-gradient karaoke look); its `node_modules` is a **junction** into the vendored install at `..\Video Production\vendor\remotion` (machine setup, not pip). `pipeline/video.py` renders `Output/<Title - Artist>/<base>.mp4` from the folder's MP3 + `.json` lyrics — via the done-screen "🎬 Render lyric video" button or `scripts\render_video.py "<song folder>"`; `scripts\smoke_video.py` is the ~1-min live check. Two sharp edges, learned live: always pass Remotion explicit arguments (a bare `remotion render` *starts a render* instead of printing help), and keep all paths handed to the CLI absolute (relative `--public-dir` resolves against `video/`, and the missing dir silently renders without audio assets until a 404 kills the run).

M5 (user-approved scope extension, 2026-06-10 — also overrides the §4 no-visual-stream-download non-goal; spec in `docs/superpowers/specs/2026-06-10-video-panel-layout-design.md`): a second render layout — the original music video letterboxed on the left ~75% of the frame with a Spotify-style scrolling lyrics tab beside it (`video/src/VideoPanel.tsx`, composition `VideoPanel`; the M4 `LyricVideo` layout stays). Stage 1 now also downloads the **video-only** stream ≤1080p (`download.download_video`; failure is non-fatal — warn and continue, FR-011 spirit) and `_finish` keeps it as `<base>.video.<ext>` in the song folder. `render_lyric_video(..., layout="panel")` renders `<base> [video+lyrics].mp4` — done-screen "🎬 Render video + lyrics panel" button or `scripts\render_video.py --layout panel`. The MP3 stays the only audio track (the video is muted), so lyric timing is identical to the lyric files. Folders processed before M5 are rescued by `fetch_video()`, which recovers the song's URL from `logs/runs.jsonl`; `scripts\smoke_video.py` checks both layouts.

M6 (user-approved scope extension, 2026-06-10; spec in `docs/superpowers/specs/2026-06-10-video-visual-redesign-design.md`): a purely visual rework of both compositions in the Apple Music lyrics-view direction — pipeline flow, outputs, and naming unchanged. `video/src/theme.tsx` (the spec's `theme.ts`; the JSX component needs `.tsx`) is the shared design language: `Colorwash` (near-black base + 2–3 huge blurred palette blobs on ~40 s drift cycles, replacing `Gradient`), the dim+blur inactive-line treatment, and the shared scroll easing. All chrome is deleted (title card, header bar, progress bars, panel border/divider); both layouts are left-aligned scrolled lyric stacks with fixed line slots, and the panel's video floats inset with rounded corners on the wash. `pipeline/video.py` extracts a per-song palette from the source video (`extract_palette`: ffmpeg 1×1-px samples at five timestamps, `_tune_color` clamps into a dark text-safe HLS band, near-duplicate hues dropped) and passes it as the `palette` prop; the lyrics-only layout looks up the `.video.*` file best-effort just for color. `DEFAULT_PALETTE` (mirrored in `theme.tsx` — keep them in sync) covers every failure: extraction must never raise out of the render path. Acceptance bar is the user's eyeball of one full-song render per layout (NFR-010). Renders default to the Radeon GPU (`--gl=angle --chrome-mode=chrome-for-testing`; the default headless shell ignores GPUs — Chrome for Testing lives in the vendored `.remotion` dir, downloaded once) plus laptop-freeze guardrails added 2026-06-11: `--concurrency=4`, a 2 GiB OffthreadVideo cache cap, below-normal subprocess priority (Windows children inherit it), and the Colorwash blobs are eased radial gradients, not `filter: blur(160px)` — the blur was the most expensive paint per frame; keep it that way. Verified live: panel preview 301 frames went ~415 s (software) → 55 s (GPU). `scripts\render_video.py --cpu` / `--concurrency N` override.

All specs live under `docs/prd/youtube-audio-lyrics-pipeline/`:

- **[HANDOFF.md](docs/prd/youtube-audio-lyrics-pipeline/HANDOFF.md)** — lean build brief; read this first.
- **[PRD.md](docs/prd/youtube-audio-lyrics-pipeline/PRD.md)** — source of truth (v1.0.0, final). Requirements are traced by ID (`FR-###` / `NFR-###`); a requirement's acceptance criteria (§8/§9) are its Definition of Done.
- **[TASKS.md](docs/prd/youtube-audio-lyrics-pipeline/TASKS.md)** — phased, dependency-ordered work plan. Work top to bottom; expand a task into sub-tasks only when you pick it up, not before.

## What this builds

A local, single-user **Streamlit** app (Windows 11) that turns one English-language YouTube music-video URL into the raw ingredients for a lyric video: a **320 kbps MP3** plus **line-level timestamped lyrics** in four formats (`.txt`, `.srt`, `.lrc`, `.json`).

## Architecture (the pipeline)

A single-screen Streamlit UI (`app.py`, session-state machine) driving a staged pipeline; each stage is a UI-agnostic module in `pipeline/`:

1. **Download + metadata** (`pipeline/download.py`) — `yt-dlp` pulls best audio and reads title/artist/duration; `clean_title()` strips "(Official Video)"-style noise from the default title guess. M5 also pulls the video-only stream (≤1080p) for the optional panel render — non-fatal if it fails.
2. **Transcode** (`pipeline/transcode.py`) — `ffmpeg` → 320 kbps MP3, into the per-run `work/` dir.
3. **Metadata confirm (always pauses)** — show editable Title/Artist before any lyrics lookup (FR-015). This pause is mandatory on every run.
4. **Synced-lyrics lookup (fast path)** (`pipeline/lyrics.py`) — `syncedlyrics` aggregator across LRCLIB + NetEase/Musixmatch/Megalobiz, using the confirmed metadata; also owns LRC parsing. The user can reject a wrong-version match and re-search or force transcription.
5. **Transcription fallback (slow path, on a miss or "Skip → transcribe")** (`pipeline/transcribe.py` + `transcribe_worker.py`) — Demucs isolates vocals, then WhisperX large-v3 (CPU/int8) with VAD + forced alignment → line-level timestamps, marked machine-transcribed. **Each stage runs in a child process so model RAM frees between stages (NFR-006) — keep it that way.** The worker gates first on language (FR-014, detected on a mid-track vocals slice; non-English → warn & stop) and post-filters hallucinated lines via a vocals-stem energy gate (FR-016). Afterwards `pipeline/correct.py` auto-corrects the transcription against online lyrics (R-004): a synced candidate that matches with a near-constant per-line offset is adopted wholesale, shifted onto this audio's timeline (`synced_aligned` — absorbs music-video intros); otherwise close-matching lines get their words replaced while keeping WhisperX timing (`plain_corrected`); if nothing validates, the raw transcription is kept — the corrector must never lose or block a run.
6. **Write outputs** (`pipeline/formats.py`, `pipeline/outputs.py`) — the four lyric formats plus the MP3 into the collision-safe per-song folder; `pipeline/runlog.py` appends per-run metrics to `logs/runs.jsonl`.
7. **Lyric video (optional, M4/M5)** (`pipeline/video.py` + `video/` Remotion project) — renders, on demand (done-screen buttons or `scripts/render_video.py`), either the lyrics-only `<base>.mp4` (M4) or the M5 `<base> [video+lyrics].mp4` panel layout from the folder's MP3 + `.json` lyrics + `.video.*` source video.

Two lyrics paths drive the design: the synced path is near-instant and accurate; the transcription path is slow (~10–30 min/song on CPU) and runs only when the lookup misses. Maximizing synced-source coverage is how you keep off the slow path. Partial-failure isolation is required — if lyrics can't be produced, the MP3 must still be saved (FR-011).

## Hard constraints (decided — do not violate)

- **CPU-only transcription, by decision.** The user's GPU is AMD (RX5500M); WhisperX/CTranslate2 GPU-accelerate only on NVIDIA CUDA. Do **not** add GPU acceleration to transcription — the PRD evaluated and rejected the AMD paths (Q-003). Transcription runs on the Ryzen 7 4800H at int8. Budget: 16 GB RAM, 50 GB+ disk. *(Q-003 is about transcription only: the Remotion render stage **does** use the Radeon via Chrome ANGLE/D3D11 — user-approved 2026-06-11, see M6.)*
- **Quality > speed (NFR-010).** When they conflict, choose the more accurate option. The ≤5 min/song figure is a *soft* target; the slow transcription path is an accepted tradeoff. Line timing target is ±0.2s on the synced path.
- **Local + free only.** The only network calls are the YouTube download and the lyrics lookup. No paid APIs, no telemetry; transcription stays local (NFR-005).
- **English-only.** Detect non-English and **warn + stop** (FR-014) — never emit wrong-language lyrics.
- **Never silently overwrite.** On a `Title - Artist` folder/name collision, warn and write versioned files (FR-012).

## Output layout

One subfolder per song named `Title - Artist`, containing the MP3 and the four lyric files, all sharing that base name. Line-level end times are derived from the next line's start (last line ends at track end). Exact per-format spec is in PRD §7.

## Non-goals (do not build)

No video rendering/assembly, no visual-stream download, no batch/playlists (one URL at a time), no word-level/karaoke highlighting (line-level only), no translation/annotation/in-app lyrics editor, no mobile/web-hosted/multi-user. Anything not stated as in-scope is out of scope — do not infer scope from omission.

## Toolchain & commands

- **Run tests (offline):** `.venv\Scripts\python.exe -m pytest tests -q` — includes Streamlit `AppTest` render checks of all four UI states. Run a single file with `-q tests\test_lyrics.py`.
- **Live end-to-end smoke (network):** `.venv\Scripts\python.exe scripts\smoke_m1.py [URL "Title" "Artist"]` — real download + lyrics search into temp dirs; self-cleaning.
- **Transcription-path smoke (network + heavy CPU):** `.venv\Scripts\python.exe scripts\smoke_m2.py [--model tiny] [--non-english]` — real Demucs + WhisperX on a trimmed clip; `--model tiny` for fast plumbing checks, default large-v3 takes minutes; `--non-english` verifies the FR-014 stop.
- **Run the app:** double-click `Launch Lyrics Pipeline.bat`, or `.venv\Scripts\python.exe -m streamlit run app.py`. `.streamlit/config.toml` pins it to localhost and disables telemetry (NFR-005) — keep it that way.
- **Update yt-dlp alone (NFR-007):** double-click `Update yt-dlp.bat`. `requirements.txt` deliberately gives yt-dlp a `>=` floor, not an exact pin — it breaks when YouTube changes.
- Deps are pinned in `requirements.txt` (Python 3.12.10 venv). `ffmpeg` is an external binary on PATH (WinGet install), not a pip dep.
- The project path contains spaces — quote absolute paths in shell commands.
- Runtime dirs (created on demand, safe to delete): `work/` (per-run temp), `Output/` (per-song results), `logs/runs.jsonl` (per-run metrics).

## Working order

Build **M1 (synced-lyrics happy path) fully before M2 (transcription fallback)**, then M3 (polish). Trace every change to a requirement ID; its acceptance criteria are the DoD. When a requirement is ambiguous, check the relevant PRD section; if still unclear, ask rather than assume.
