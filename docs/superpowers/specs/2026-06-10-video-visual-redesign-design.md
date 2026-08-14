# Lyric-Video Visual Redesign (Apple Music direction) — Design

- **Date:** 2026-06-10
- **Status:** Implemented 2026-06-10 (tests + bundle check + smoke green); awaiting the user eyeball verdict on full-song renders — that is the acceptance bar (§7)
- **Scope:** M6 — purely visual rework of both Remotion compositions plus a palette-extraction helper in the render driver. Pipeline flow, outputs, file naming, and UI mechanics are unchanged.

## Problem

The M4/M5 renders work but look generic (stock dark gradient, default-ish type, visible chrome). The user wants a modern, minimalistic look drawn from real products known for UI/UX.

## Decisions made during brainstorming

| Question | Decision |
|---|---|
| Anchor aesthetic | **Apple Music lyrics view** (chosen over Spotify, Vercel/Linear editorial, kinetic typography) |
| Scope | **Both layouts** — `LyricVideo` (full-frame) and `VideoPanel` share one design language |
| Background color | **Per-song palette extracted from the source video** at render time; designed fallback palette otherwise |
| Direction (visual mockup round) | **A — Faithful Apple Music**: left-aligned lyric stack, heavy rounded type, inactive lines dimmed *and blurred*, vivid wash, zero chrome |

## 1. Palette extraction (`pipeline/video.py`)

- New private helper `extract_palette(video_path: Path) -> list[str] | None`:
  - ffmpeg samples 5 frames at the 10/30/50/70/90% timestamps, each scaled to 1×1 px (`scale=1:1`) and emitted as raw `rgb24` bytes → five average RGB triplets.
  - `_tune_color(rgb) -> str` (pure function): convert to HLS; clamp lightness into a dark, text-safe band (≈0.16–0.34); floor saturation (≈0.35) so washes don't go muddy; return hex.
  - Near-duplicate hues are dropped (hue distance threshold); keep the first 2–3 distinct colors.
- `DEFAULT_PALETTE` constant (deep violet / slate / indigo trio) used whenever there is no `.video.*` file or anything in extraction fails. **Extraction must never raise out of the render path.**
- Both layouts use it: the panel layout already has the video; the lyrics-only layout looks up `find_video_file()` best-effort just for color.

## 2. Shared design language (`video/src/theme.ts`)

New module imported by both compositions:

- `FONT`: `'"Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif'` — heavy weights (650–800) approximate SF Pro Rounded on Windows.
- `DEFAULT_PALETTE` (mirrors the Python constant) so props without `palette` still render.
- `Colorwash` component (replaces `Gradient`): a near-black base (`#0a0a12`) with 2–3 huge, heavily blurred radial blobs in the palette colors drifting on slow sine paths (full drift cycle ≈ 40 s). Calm, never busy.
- Inactive-line treatment constants: opacity ≈0.35 at distance 1 falling to ≈0.12, blur 2px at distance 1 growing ≈2px per line of distance (capped ~8px).
- Easing/spring helpers shared by both stacks.

## 3. `LyricVideo` (full-frame) redesign

**Deleted chrome:** the "♪ Lyric video ♪" title card, the top `Title — Artist` header bar, and the bottom progress bar.

- **Intro (before first line):** title ≈96px weight 800 white, artist ≈40px at 60% white, positioned where the lyric stack lives (left-aligned, optically centered vertically); eases out as the first line arrives.
- **Lyric stack:** left-aligned column occupying the left ~60% of frame width (left margin ≈160px, right wrap room), all lines rendered, spring-scrolled so the active line rests at the optical vertical center (same scroll model as the M5 panel: ease-out over ≈0.45 s on line change).
  - Active line: pure white, ≈64px, weight 800, letter-spacing −1px.
  - Inactive lines: theme dim/blur by distance (§2).
  - Fixed 160px line slots keep the scroll math exact; two-line wraps fit inside a slot at this size.
- **Outro:** the wash simply continues after the last line; no end card.

## 4. `VideoPanel` redesign

- `Colorwash` fills the entire 1920×1080 frame (flat graphite panel and 1px border deleted).
- **Video as floating element:** still `object-fit: contain` within the left region, but inset (≈48px margins), with ~24px rounded corners and a soft ambient shadow (`0 24px 80px rgba(0,0,0,0.45)`), floating on the wash.
- **Right tab (480px):** no border, no divider — a darker scrim (`rgba(8,8,16,0.45)`) over the wash for text contrast. Header is type only: title ≈28px weight 800, artist below at 60% white. The lyric stack matches §3 scaled down: active ≈30px weight 800, same dim/blur model, same fixed-slot scroll (slot ≈104px as today).
- Progress bar deleted here too. Edge fades at the stack viewport's top/bottom stay (they read as depth, not chrome).

## 5. Props & driver wiring

- `_props_for()` adds `palette: list[str]`; `render_lyric_video()` resolves it once per render (extract → tune → fallback).
- TS prop types: `LyricVideoProps` gains `palette?: string[]` (default `DEFAULT_PALETTE`), `VideoPanelProps` inherits.
- `Root.tsx` defaultProps updated minimally (no `palette` key — exercises the default path).
- No changes to app.py, scripts CLI surface, output naming, or any pipeline stage ordering.

## 6. Error handling

| Failure | Behavior |
|---|---|
| No `.video.*` for the song | `DEFAULT_PALETTE` — render proceeds |
| ffmpeg missing/fails/odd codec | `DEFAULT_PALETTE` — render proceeds, no error surfaced |
| Old props file without `palette` | TS default kicks in |
| Extreme source colors (near-black/white video) | `_tune_color` clamps into the text-safe band |

## 7. Testing & verification

- **Unit (offline):** `_tune_color` clamps/floors correctly (dark, light, gray inputs); palette parsing from mocked ffmpeg bytes; dedupe of similar hues; fallback when ffmpeg errors; `_props_for`/render flow includes `palette` (driver tests' fake Popen already captures props).
- **Bundle check:** `remotion compositions` lists both compositions after the TSX changes.
- **Smoke:** existing two-layout `scripts/smoke_video.py` (the test-pattern clip also exercises real palette extraction in the panel pass).
- **Eyeball:** one real full-song render per layout to judge wash, type, and blur — user verdict is the acceptance bar.
- Render-time cost of per-line `filter: blur` is accepted (NFR-010 quality > speed); the blur constants live in `theme.ts` if they ever need softening.

## Out of scope

- Word-level/karaoke timing or animation (PRD §4 stands).
- Album-art fetching or any new network call.
- App UI (Streamlit) changes; CLI flags; new layouts.
- Light mode / theme options — one designed look.
