# Video + Lyrics Panel Render Layout — Design

- **Date:** 2026-06-10
- **Status:** Approved 2026-06-10; implemented as M5
- **Scope authority:** User-approved scope extension (M5). Extends the M4 override of PRD §4: in addition to video *rendering* (M4), this consciously overrides the "no visual-stream download" non-goal. Everything else in PRD §4 still holds (no batch, line-level only, English-only).

## Problem

The M4 lyric video is lyrics-only on a gradient background. The user wants a second render layout where the **original YouTube music video plays on ~75% of the frame** with the lyrics in a panel beside it.

## Decisions made during brainstorming

| Question | Decision |
|---|---|
| Replace or add? | **Add as a second option.** The existing `LyricVideo` composition and button stay unchanged. |
| Panel behavior | **Auto-scrolling list, current line highlighted** (Spotify-style). Line-level only — no word/karaoke highlighting (PRD §4 non-goal stands). |
| When to fetch the video | **During every pipeline run** (stage 1). Failure is non-fatal. |
| Render mechanism | **Approach A: all-in-Remotion.** Muted `<OffthreadVideo>` + the pipeline's 320 kbps MP3 as the only audio track. |
| Rejected alternatives | B: render panel only in Remotion, composite with ffmpeg `hstack` (two-step glue, visual seam, harder to test). C: mux YouTube's own audio (breaks the one-timeline guarantee and the 320 kbps output spec). |

## 1. Pipeline — video download (stage 1)

New `download_video(url: str, work_dir: Path) -> Path` in `pipeline/download.py`, called from `app.py` stage 1 after the audio download + transcode succeed.

- yt-dlp format: `bestvideo[height<=1080][ext=mp4]/bestvideo[height<=1080]/bestvideo` — video-only stream (no audio track), capped at 1080p (the layout slot is ~1440×810, so 1080p is already oversampled), preferring MP4/h264 (fastest decode in Remotion's ffmpeg-backed `OffthreadVideo`).
- Same option hygiene as `download_audio`: `noplaylist`, `windowsfilenames`, `quiet`, `noprogress`, `no_warnings`; outtmpl `source_video.%(ext)s` in the run's `work/` dir.
- **Non-fatal on failure (FR-011 spirit):** the UI shows a warning, `run["video_path"] = None`, and the run proceeds normally — MP3 + lyrics are unaffected; only the panel render becomes unavailable for that song (until fetched on demand, §4).
- Network policy (NFR-005) is unchanged in kind: the video stream is part of the YouTube download; no new endpoints.

## 2. Outputs — placing the video file

`pipeline/outputs.py` gains `place_video(...)` mirroring `place_mp3`: the video is moved into the song folder as **`<base>.video.<ext>`** (e.g. `Halo - Beyoncé.video.mp4`), where `<base>` is the run's collision-resolved base name including any version suffix (FR-012; never overwrite). The `.video.` infix guarantees it can never collide with a rendered `<base>.mp4` or `<base> [video+lyrics].mp4`.

Disk cost: ~50–150 MB per song folder at ≤1080p.

## 3. Remotion — new `VideoPanel` composition

New `video/src/VideoPanel.tsx`, registered in `Root.tsx` as a second `<Composition id="VideoPanel">` (1920×1080@30, same `calculateMetadata` duration logic). `LyricVideo` is untouched.

- **Props:** `LyricVideoProps` + `videoFile: string` (file name inside the Remotion public dir, like `audioFile`).
- **Left region (~75%, 1440×1080):** `<OffthreadVideo muted src={staticFile(videoFile)}>` letterboxed/centered (`object-fit: contain`) over the existing dark gradient. If the video stream runs slightly shorter than the composition, the last frame holds — acceptable, both streams come from the same YouTube source.
- **Right panel (480px):** header with title/artist, divider, then the full lyrics column. Scroll position is driven by the current line index: a spring-animated `translateY` keeps the active line vertically centered in the panel. Active line bright and slightly larger; past/future lines dimmed. Before the first line starts, the panel shows the dimmed list from the top (no title card in this layout — the video is the visual; the header carries title/artist).
- **Audio:** `<Audio src={staticFile(audioFile)}>` — the 320 kbps MP3, exactly as `LyricVideo` does. The video contributes no audio, so the rendered sound and the lyric timestamps share one timeline by construction.
- Progress bar spans the bottom of the full frame, as today.

## 4. Render driver + CLI (`pipeline/video.py`, `scripts/render_video.py`)

- `render_lyric_video(...)` gains `layout: Literal["lyrics", "panel"] = "lyrics"`. For `"panel"` it:
  - finds the newest `<base>.video.*` matching the chosen base (new helper `find_video_file(folder, base)`); raises a clear error naming the fix if absent;
  - adds `videoFile` to the props and renders composition `VideoPanel`;
  - writes **`<base> [video+lyrics].mp4`**, versioned via the existing never-overwrite logic, so the two layouts' outputs are distinguishable at a glance.
- **Old-folders rescue:** new `fetch_video(folder) -> Path` looks up the song's URL in `logs/runs.jsonl` (newest successful record matching the folder's title/artist), downloads the video into the song folder as `<base>.video.<ext>`, and returns it. If no URL is recoverable, the error message says to re-run the song once through the app.
- `scripts/render_video.py` gains `--layout panel` (default `lyrics`). The no-args folder listing notes which folders have a `.video.` file.
- All paths handed to the Remotion CLI stay absolute; explicit arguments always (the two M4 sharp edges still apply).

## 5. App UI (done screen)

A second button next to the existing one: **"🎬 Render video + lyrics panel"**, shown whenever the run produced lyrics.

- Folder has `<base>.video.*` → renders directly, streaming Remotion progress like today.
- No video file but the URL is recoverable (this run's state, or `runs.jsonl`) → button fetches the video first, then renders, with status for both phases.
- Neither → button is disabled with an explanatory caption.

No new settings. A render or fetch failure never touches the song's other files (FR-011 spirit, as M4).

## 6. Error handling summary

| Failure | Behavior |
|---|---|
| Video download in stage 1 | Warn in UI, continue run; MP3 + lyrics unaffected |
| Video missing at render time | Clear error / disabled button with re-run or fetch-on-demand path |
| Fetch-on-demand fails | Error surfaced; song files untouched |
| Remotion render fails | As M4: error with output tail; never touches existing files |
| Odd codec (webm/vp9 fallback) | Handled by `OffthreadVideo`'s ffmpeg decode |

## 7. Testing

- **Unit (offline, mocked):** yt-dlp format/options for `download_video`; `place_video` naming + FR-012 versioning; `find_video_file` (newest, base-matched); panel props include `videoFile`; command builds with `VideoPanel` and the `[video+lyrics]` output name; `runs.jsonl` URL lookup (hit, miss, malformed lines).
- **AppTest:** done screen shows the panel button; disabled state + caption when no video and no recoverable URL.
- **Smoke (`scripts/smoke_video.py`):** extended to also render ~4 s of `VideoPanel` against an ffmpeg-generated test-pattern clip placed in the temp song folder (no extra network), ffprobe-verified like the M4 check.

## 8. Performance & docs

- Panel renders are expected to be a few times slower than lyrics-only (per-frame video decode on CPU). Accepted under NFR-010 (quality > speed).
- `CLAUDE.md` and `TASKS.md` get an M5 section recording this scope extension, mirroring how M4 was documented.

## Out of scope

- Word-level/karaoke highlighting (PRD §4 stands).
- Batch fetching videos for all existing folders.
- Any change to the four lyric formats, the MP3 output, or the existing `LyricVideo` look.
- Layout variants (video-as-background, top/bottom split) — the side panel is the design.
