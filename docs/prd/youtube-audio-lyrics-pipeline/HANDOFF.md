# YouTube Audio & Timestamped Lyrics Pipeline — Implementation Handoff

> **Read me first.** This is the lean entry point for building the pipeline. It carries everything
> you need to start. For full detail on any item, open the linked section in `PRD.md` **only when
> you begin the task that needs it** — do not load the whole PRD up front.

**Source of truth:** `./PRD.md` (version 1.0.0, status: final) · **Tasks:** `./TASKS.md`

---

## What & why

A small, locally-run **Streamlit** app that takes the URL of an **English-language** YouTube music video and produces the raw ingredients for a **lyric video**: the song's audio as a **320 kbps MP3**, plus the lyrics with **line-level timestamps** in four formats (txt, SRT, LRC, JSON). The user makes lyric videos and processes several songs a day; today they juggle a separate MP3 site and a separate (un-timed) lyrics site and hand-time everything, which is the bottleneck. To get accurate timing the tool searches **multiple online synced-lyrics sources first**, and only on a miss falls back to **local AI transcription**. (PRD §1–2)

## Goals

- **Primary:** from one pasted URL, produce audio + timed lyrics that drop into a lyric-video editor with **at most a moderate timing touch-up — never a full manual re-timing**.
- **Secondary:** a maintainable, fully-local pipeline using free/open tools, where **output quality takes precedence over speed**.

## Non-goals (do NOT build these)

- Non-English songs — detect and **warn + stop** (FR-014).
- Word-level / per-word karaoke highlighting — **line-level only**.
- Batch processing / playlists — **one URL at a time**.
- Video rendering / assembly — **ingredients only**; the user builds the video in their editor.
- Visual (video-stream) download or editing — **audio only**.
- Lyrics translation, annotation, or an in-app lyrics editor.
- Publishing, licensing, or rights clearance — produces **local files only** (see PRD R-002).
- Mobile app, web-hosted service, or multi-user.

<!-- Non-goals are mandatory. Anything not stated as in-scope is out of scope; do not add it. -->

## Success metrics (build the instrumentation for these)

- **Primary:** ≥ 85% of songs ready with **≤ moderate touch-up** (no full re-timing).
- **Input:** per-line timing within **±0.2s** on the synced path; synced-lyrics hit rate ≥ 50%; end-to-end success ≥ 95% MP3 / ≥ 90% lyrics.
- **Guardrail:** processing time ≤ 5 min/song on the Ryzen 7 4800H — **soft target**, quality wins (NFR-010); MP3 at **320 kbps**.
- **Logging:** record per run the lyrics source (synced vs transcribed), processing time, and success/failure. ±0.2s alignment and cleanup effort are manual spot-checks. (PRD §3, §10)

## Tech stack & hard constraints

- **Python**; **Streamlit** local web app (opens in browser); **Windows 11** (10 likely compatible).
- **CPU-only.** The RX5500M (AMD) cannot accelerate CTranslate2/WhisperX (CUDA-only). Run transcription on the Ryzen 7 4800H (int8). Budget: 16 GB RAM, 50 GB+ disk.
- **Pipeline:** `yt-dlp` (download + metadata) → `ffmpeg` (320 kbps MP3) → **multi-source synced lyrics** (`syncedlyrics`: LRCLIB + NetEase/Musixmatch/Megalobiz) → on miss, **Demucs** vocal isolation + **WhisperX large-v3** (CPU/int8) with VAD + forced alignment → write 4 lyric formats.
- **Always pause** for a metadata (Title/Artist) confirm/edit step before the lyrics lookup (FR-015).
- **Output layout:** a per-song subfolder named **"Title - Artist"**; MP3 + 4 lyric files share that base name; **never silently overwrite** — warn and write versioned files (FR-009, FR-012).
- Fully local except the YouTube download and lyrics lookup (always-online is fine); **no paid APIs**.
- **Packaging:** Python venv + a double-click `.bat` launcher that starts the Streamlit app. (PRD §10–11)
- **Design doc:** not required for v1 — the stack and approach are specified inline.

## Milestone roadmap

| Phase | Goal | Key requirement IDs |
| ----- | ---- | ------------------- |
| M1 | Synced-lyrics happy path (Streamlit) | FR-001, FR-003, FR-004, FR-005, FR-007, FR-009, FR-010, FR-012, FR-015 |
| M2 | Transcription fallback (quality stack: Demucs + WhisperX) | FR-006, FR-016, FR-008, FR-011, FR-014 |
| M3 | Polish | FR-002, FR-013, FR-018 |

## How to work here

- Read this brief first; open the relevant `PRD.md` section only when you start that task.
- Each requirement's **acceptance criteria are its Definition of Done** — find them by ID in PRD §8/§9.
- **Respect the non-goals.** Do not add unrequested features or infer scope from omission.
- **Quality over speed** (NFR-010): when they conflict, choose the more accurate option.
- Work milestone by milestone. Expand each high-level task in `TASKS.md` into concrete sub-tasks **when you pick it up**, not before.
- When a requirement is ambiguous, check the PRD section; if still unclear, ask rather than assume.

## PRD index (jump to detail on demand)

| #  | Section                                  | Anchor / link             |
| -- | ---------------------------------------- | ------------------------- |
| 1  | Overview / TL;DR                         | `PRD.md#1-overview--tldr` |
| 2  | Problem & Context                        | `PRD.md#2-problem--context` |
| 3  | Goals & Success Metrics                  | `PRD.md#3-goals--success-metrics` |
| 4  | Non-Goals / Out of Scope                 | `PRD.md#4-non-goals--out-of-scope` |
| 5  | Target Users & JTBD                      | `PRD.md#5-target-users--jobs-to-be-done` |
| 6  | User Stories & Use Cases                 | `PRD.md#6-user-stories--use-cases` |
| 7  | Solution Overview & UX                   | `PRD.md#7-solution-overview--ux` |
| 8  | Functional Requirements                  | `PRD.md#8-functional-requirements` |
| 9  | Non-Functional Requirements              | `PRD.md#9-non-functional-requirements` |
| 10 | Technical Considerations & Dependencies  | `PRD.md#10-technical-considerations-dependencies--constraints` |
| 11 | Release & Rollout Plan                   | `PRD.md#11-release--rollout-plan` |
| 12 | Risks, Assumptions & Open Questions      | `PRD.md#12-risks-assumptions--open-questions` |
| 13 | Appendix, References & Glossary          | `PRD.md#13-appendix-references--glossary` |
