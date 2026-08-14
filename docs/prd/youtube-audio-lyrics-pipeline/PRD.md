---
title: "YouTube Audio & Timestamped Lyrics Pipeline"
status: final # draft | problem-review | solution-review | final | in-build | launched
version: 1.0.0
last_updated: "2026-06-09"
owner: "Pranita"
reviewers: [] # e.g. [eng-lead, design-lead, data]
preset: full # full | brief
overall_confidence: high # low | med | high
links:
  designs: ""
  tickets: ""
  research: ""
---

# YouTube Audio & Timestamped Lyrics Pipeline — Product Requirements Document

| Field      | Value |
| ---------- | ----- |
| Status     | Final |
| Version    | 1.0.0 |
| Owner      | Pranita |
| Reviewers  | TBD |
| Updated    | 2026-06-09 |
| Designs    | — |
| Tickets    | — |
| Research   | — |

---

## 1. Overview / TL;DR

A small, locally-run Streamlit app that takes the URL of an English-language YouTube music video and produces the raw ingredients for a lyric video: the song's audio as a 320 kbps MP3, plus the lyrics with line-level timestamps written in four formats (plain text, SRT, LRC, JSON). To get accurate timing it uses a hybrid strategy — it first searches multiple online synced-lyrics sources, and only if none match does it fall back to local AI transcription (WhisperX large-v3 with Demucs vocal isolation). It runs on the user's own Windows machine using free/open tools; the user confirms the detected song title/artist before lookup, and output quality is prioritized over speed. `[CONFIRMED]`

---

## 2. Problem & Context

**Problem statement.** The user produces lyric / karaoke-style music videos for YouTube and needs two raw ingredients per song: a clean offline audio copy and an accurately time-synced lyrics file. Getting these today means juggling a separate "YouTube to MP3" site and a separate lyrics site by hand, and the lyrics found that way are almost never timestamped — so the timing has to be transcribed and aligned manually, which is the slow, tedious bottleneck in producing a lyric video. `[CONFIRMED]`

**Evidence.** Direct user request. The user makes lyric music videos and processes **several songs a day**, currently stitching together a separate MP3 site and a separate lyrics site manually. Demand beyond this single user is explicitly not a goal (personal-use tool). `[CONFIRMED]`

**Why it matters.** Accurately timed lyrics are the gating input for a lyric video; producing them manually (listening and typing timestamps line by line) is slow enough to throttle how many videos get made. Automating audio + timed-lyrics extraction removes the most tedious step and is the difference between making a few videos and many. `[CONFIRMED]`

**Why now.** The enabling pieces are mature and free: robust YouTube downloaders (yt-dlp), open lyrics databases that serve synced `.lrc` data, and local speech-to-text models good enough to transcribe with timestamps on consumer hardware. The user has hardware on hand and wants it to run locally rather than depending on a paid service. `[CONFIRMED]`

**Downstream-use note (copyright).** The intended end use — publishing lyric videos of commercial songs to YouTube — reuses copyrighted sound recordings and lyrics. This pipeline only produces local files; whether and how the resulting videos may be published (licensing, fair use, YouTube Content ID) is the user's responsibility and is tracked as a risk (R-002), not something this tool resolves. `[CONFIRMED]`

---

## 3. Goals & Success Metrics

**Objectives**

- User objective: from one pasted URL, get audio + timed lyrics that drop into a lyric-video editor with at most a *moderate* timing touch-up — never a full manual re-timing.
- Project objective: a maintainable local pipeline that runs entirely on the user's own machine using free/open tools, fast enough to feed daily video production.

**Success metrics**

| Type      | Metric                                                      | Target & timeframe                                  | Baseline |
| --------- | ---------------------------------------------------------- | --------------------------------------------------- | -------- |
| Primary   | Manual timing-cleanup needed per song                      | ≥ 85% of songs ready with **≤ moderate touch-up** (no full re-timing) `[CONFIRMED]` (intent); target value `[ASSUMPTION]` | 0 (new) |
| Input     | Per-line timing error vs the sung line                     | Line start within **±0.2s** on the synced-lyrics path; best-effort on the transcription path `[CONFIRMED]` (target) — *ambitious for automated alignment; see R-004* | n/a |
| Input     | Synced-lyrics hit rate (found online before falling back)   | ≥ 50% of songs matched without transcription `[ASSUMPTION]` | n/a |
| Input     | End-to-end success (valid URL → files produced)            | ≥ 95% produce a playable MP3; ≥ 90% also produce a lyrics file `[ASSUMPTION]` | n/a |
| Guardrail | Processing time for a typical 3–4 min song (CPU)            | ≤ 5 min end-to-end on the Ryzen 7 4800H `[CONFIRMED]` | n/a |
| Guardrail | Audio fidelity                                              | MP3 at 320 kbps, no truncation/clipping `[CONFIRMED]` | n/a |

**Note on the ±0.2s target.** This precision is the user's stated requirement for clean on-screen sync. It is realistic on the **synced-lyrics path** but aggressive on the **transcription fallback**, where it relies on WhisperX forced alignment plus Demucs vocal isolation. Because quality takes precedence over speed (NFR-010), that extra compute is accepted even though it pushes the transcription path past the soft ≤5 min target. Tracked in R-004.

---

## 4. Non-Goals / Out of Scope

- Non-English songs — out of scope for this release; the pipeline assumes English input. `[CONFIRMED]`
- Word-level / karaoke-style per-word highlighting — line-level timestamps only; a possible future addition. `[CONFIRMED]`
- Batch processing / playlists — one URL at a time; no queue in this release. `[CONFIRMED]`
- Video rendering / assembly — the tool outputs ingredients only (audio + lyrics files); the user assembles the lyric video in their own editor. `[CONFIRMED]`
- Video (visual) stream download or editing — audio only. `[CONFIRMED]`
- Lyrics translation, annotation, or an in-app lyrics editor. `[ASSUMPTION]`
- Publishing, licensing, or rights clearance — the tool produces local files only; how the resulting videos are published is the user's responsibility (see R-002). `[CONFIRMED]`
- Mobile app, web-hosted service, or multi-user deployment. `[CONFIRMED]`

---

## 5. Target Users & Jobs-to-be-Done

**Primary persona(s)**

- **Pranita — the lyric-video creator.** A single individual making lyric / karaoke music videos for YouTube, running the tool on her own Windows 11 laptop for personal production. Processes several songs a day; wants minimal fuss per song. Comfortable either running a script/command or using a one-click app. Hardware: AMD Radeon RX5500M GPU, AMD Ryzen 7 4800H CPU (8c/16t). `[CONFIRMED]`

**Secondary / affected**

- None in this release — single-user, local tool. `[CONFIRMED]`

**Jobs-to-be-Done**

- When I find an English song on YouTube, I want its audio and accurately timed lyrics in one step, so I can make a lyric video without timing it by hand.
- When a song isn't in any lyrics database, I want the tool to still produce timestamped lyrics automatically, so I'm never stuck transcribing by hand.
- When I'm producing several songs a day, I want each run to need at most a moderate timing touch-up, so the tedious part doesn't bottleneck my output.

---

## 6. User Stories & Use Cases

### US-1 — Get audio + lyrics from one URL  ·  Priority: P0
> As the user, I want to paste a YouTube URL and start one run, so that I get back an MP3 and timestamped lyrics files ready to drop into a lyric-video project.

**Acceptance criteria**

- Given a valid English-song YouTube URL, When I submit it, Then an MP3 file and separate line-level lyrics files (`.txt`, `.srt`, `.lrc`, `.json`) are saved to the output folder.
- Given the run is in progress, When each stage runs (download → lyrics lookup → transcription if needed → write), Then the interface shows which stage is active.
- Given the run completes, When I look at the result, Then the interface tells me where the files were saved and which lyrics source was used (online vs transcribed).

### US-2 — Automatic fallback when no synced lyrics exist  ·  Priority: P0
> As the user, I want the tool to transcribe the audio locally when no online synced lyrics are found, so that I still get timestamped lyrics.

**Acceptance criteria**

- Given the online lyrics lookup returns no synced match, When processing continues, Then the tool transcribes the downloaded audio locally and produces line-level timestamps.
- Given transcription is used, When the lyrics file is written, Then it is clearly marked as machine-transcribed (vs sourced).

### US-3 — Graceful handling of failures  ·  Priority: P1
> As the user, I want clear feedback when something can't be done, so that I know what happened and what I still got.

**Acceptance criteria**

- Given the audio downloads but no lyrics can be found or transcribed, When the run ends, Then the MP3 is still saved and the interface reports that lyrics could not be produced.
- Given an invalid or non-YouTube URL, When I submit it, Then I get a clear error and no partial files are left behind.

### US-4 — Predictable, organized output  ·  Priority: P1
> As the user, I want files named and placed predictably, so that I can find and pair audio with lyrics later.

**Acceptance criteria**

- Given a successful run, When files are written, Then the MP3 and lyrics files share a consistent base name derived from the song title/artist.
- Given repeated runs, When a file with the same name already exists, Then the tool does not silently overwrite — it warns and writes a new, versioned name. `[CONFIRMED]`

### US-5 — Confirm or correct song metadata  ·  Priority: P1
> As the user, I want to review and edit the detected title and artist before the lyrics lookup, so that the right version's lyrics are matched.

**Acceptance criteria**

- Given audio metadata is detected, When the run reaches lyrics lookup, Then the detected title/artist are shown and editable before the lookup proceeds. `[CONFIRMED]`
- Given I edit the title/artist, When I confirm, Then the lyrics lookup uses my corrected values.
- Given a matched lyric set looks like the wrong version, When I reject it, Then I can re-search with corrected metadata or fall back to transcription. `[CONFIRMED]`

### US-6 — Re-run without clobbering prior work  ·  Priority: P1
> As the user, I want re-processing the same song not to silently overwrite earlier files, so that I never lose hand-corrected lyrics.

**Acceptance criteria**

- Given output files for a song already exist, When I run it again, Then the tool warns and writes new, versioned files rather than overwriting. `[CONFIRMED]`

### US-7 — Reliable on awkward tracks  ·  Priority: P1
> As the user, I want long tracks and songs with instrumental gaps handled cleanly, so that I don't get truncated audio or made-up lyrics.

**Acceptance criteria**

- Given a track longer than 8 minutes, When processed, Then the full audio and full-length lyrics are produced without truncation. `[CONFIRMED]`
- Given a long instrumental intro or gap, When transcribing, Then no spurious / hallucinated lines are emitted for the non-vocal span. `[CONFIRMED]`

---

## 7. Solution Overview & UX

**Approach.** A single-screen **Streamlit** local web app (launched on the user's machine, opens in the browser). Layout: a URL field + Go button at the top, a live progress/status area for the pipeline stages, an inline **metadata-confirm step** (editable Title/Artist) that **always pauses** before the lyrics lookup, and a results panel that previews the lyrics and lists the output files with an "open folder" action. The interface hides pipeline complexity: URL in → quick confirm → files out. `[CONFIRMED]`

**Key flows.**

1. User pastes a YouTube URL and clicks Go.
2. Tool downloads the best audio stream, reads title/artist/duration metadata, and transcodes to MP3.
3. **Always pause** — show the detected Title/Artist for the user to confirm or edit.
4. On confirm, run a multi-source synced-lyrics search (LRCLIB + others) using the (possibly corrected) title/artist:
   - **Match found** → use it; if it's the wrong version, the user can reject it and re-search or force transcription.
   - **No match** → run local transcription with line-level timestamps, using voice-activity detection so instrumental sections don't produce hallucinated lines.
5. Write outputs into a **per-song subfolder named "Title - Artist"**: the MP3 plus lyrics as `.txt`, `.srt`, `.lrc`, and `.json`. If that folder already exists, write versioned files (no silent overwrite).
6. Show a summary: a short lyrics preview, the files written, the location, the lyrics source (online vs transcribed), and an "open folder" button.

**Lyrics output formats** — all four emitted per run, each fully specified below `[CONFIRMED]`:

- **Plain text** (`.txt`) — `[mm:ss] line` per line.
- **SRT** (`.srt`) — numbered subtitle blocks, `HH:MM:SS,mmm --> HH:MM:SS,mmm`; imports directly into most video editors.
- **LRC** (`.lrc`) — `[mm:ss.xx]line` synced-lyrics format (start times only).
- **JSON** (`.json`) — array of `{ start, end, text }` per line (times in seconds) for programmatic use.

For line-level SRT/JSON, each line's **end time** is derived from the next line's start (last line ends at track end). Example plain-text form:

```
[00:12] First line of the lyrics
[00:17] Second line of the lyrics
[00:21] ...
```

**Designs / prototypes.** Low-fidelity wireframes of the three screen states (Streamlit) — layout intent `[CONFIRMED]`; production styling uses Streamlit defaults (not separately specified):

```
State A — Input & progress
┌───────────────────────────────────────────────┐
│  YouTube → Audio + Timed Lyrics                │
│  YouTube URL: [______________________]  [ Go ] │
│  Progress:                                     │
│    ✔ Downloaded audio (3:48)                   │
│    ✔ Saved MP3 (320 kbps)                      │
│    … Detecting song details                    │
└───────────────────────────────────────────────┘

State B — Confirm song details (always pauses)
┌───────────────────────────────────────────────┐
│  Confirm song details                          │
│    Title:  [ Blinding Lights              ]    │
│    Artist: [ The Weeknd                   ]    │
│    (edit if the match looks wrong)             │
│        [ Look up lyrics ]   [ Skip → transcribe ] │
└───────────────────────────────────────────────┘

State C — Results
┌───────────────────────────────────────────────┐
│  Done — "Blinding Lights - The Weeknd"         │
│    Lyrics source: LRCLIB (synced) ✔            │
│    Preview:  [00:00] ...  [00:14] I been ...   │
│    Files:  .mp3  .txt  .srt  .lrc  .json       │
│    Folder: …/Output/Blinding Lights - The Weeknd │
│        [ Open folder ]        [ New song ]     │
└───────────────────────────────────────────────┘
```

---

## 8. Functional Requirements

| ID     | Requirement (state the need, not the solution) | Priority | Acceptance criteria | Traces to |
| ------ | ---------------------------------------------- | -------- | ------------------- | --------- |
| FR-001 | The system shall accept a single YouTube video URL through a simple graphical interface. | P0 | Given the app is open, When the user pastes a URL and triggers processing, Then the pipeline starts. | US-1 |
| FR-002 | The system shall validate the input and reject non-YouTube or malformed URLs with a clear message. | P1 | Given an invalid URL, When submitted, Then a readable error is shown and no files are created. | US-3 |
| FR-003 | The system shall download the song's audio and read its metadata (title, artist, duration) from the video. | P0 | Given a valid URL, When processing runs, Then audio is retrieved and metadata is captured for downstream use. | US-1, US-4 |
| FR-004 | The system shall produce the song audio as a 320 kbps MP3 file. | P0 | Given audio is downloaded, When transcoding completes, Then a playable 320 kbps MP3 `[CONFIRMED]` is saved. | US-1 |
| FR-005 | The system shall attempt to retrieve existing time-synced lyrics from an online lyrics database using the (user-confirmed) song metadata. | P0 | Given confirmed metadata, When a synced match exists, Then it is offered as the lyrics source; When the user rejects it as the wrong version, Then they can re-search or force transcription. | US-1, US-5 |
| FR-006 | The system shall fall back to local AI transcription (WhisperX large-v3, CPU) with Demucs vocal isolation and forced alignment when no synced lyrics are found. | P0 | Given no synced match, When processing continues, Then local transcription produces line-level timestamps (vocals isolated, VAD-gated) without cloud services. | US-2 |
| FR-007 | The system shall write the timestamped lyrics to separate files in four formats — plain text, SRT, LRC, and JSON (line-level), all emitted per run. | P0 | Given lyrics are obtained (either path), When writing, Then `.txt`, `.srt`, `.lrc`, and `.json` files, each with line-level timestamps, are saved separately from the MP3. | US-1 |
| FR-008 | The system shall indicate, in the output, whether lyrics were sourced online or machine-transcribed. | P1 | Given a completed run, When the user inspects the result, Then the lyrics source is stated. | US-2 |
| FR-009 | The system shall save all outputs for a song into a per-song subfolder named "Title - Artist", with the MP3 and the four lyrics files sharing that base name. | P1 | Given a successful run, When files are written, Then a "Title - Artist" subfolder contains the MP3 and `.txt`/`.srt`/`.lrc`/`.json`, all sharing the base name. | US-4 |
| FR-010 | The system shall display pipeline progress/status per stage. | P1 | Given a run in progress, When each stage executes, Then the current stage is visible to the user. | US-1 |
| FR-011 | The system shall isolate partial failures so the audio is still saved if lyrics cannot be produced. | P1 | Given lyrics lookup and transcription both fail, When the run ends, Then the MP3 is retained and the lyrics failure is reported. | US-3 |
| FR-012 | The system shall not silently overwrite existing outputs; on a name/folder collision it warns and writes versioned files. | P0 | Given an existing "Title - Artist" folder, When the song is re-run, Then the tool warns and writes new versioned files rather than overwriting. | US-4, US-6 |
| FR-013 | The system shall let the user see and/or choose the output folder. | P2 | Given the app, When the user checks settings, Then the output location is visible and changeable. | US-4 |
| FR-014 | The system shall detect non-English audio and, per the English-only scope, warn and stop (skip the song) rather than produce wrong-language lyrics. | P1 | Given a song detected as non-English, When detected, Then the tool warns and stops the run without producing lyrics. `[CONFIRMED]` | §4 |
| FR-015 | The system shall show the detected title/artist and let the user confirm or edit them before the lyrics lookup (always pause). | P0 | Given audio metadata is detected, When the run reaches lookup, Then the title/artist are shown editable and the lookup uses the confirmed values. | US-5 |
| FR-016 | The system shall avoid emitting lyrics for non-vocal spans during transcription (voice-activity detection). *Satisfied by the chosen stack: WhisperX VAD + Demucs vocal isolation.* | P2 | Given a long instrumental intro/gap, When transcribing, Then no spurious lines are produced for that span. | US-7 |
| FR-017 | The system shall process long tracks (e.g. >8 min) without truncating audio or lyrics. | P1 | Given an 8–12 min track, When processed, Then full audio and full-length lyrics are produced. | US-7 |
| FR-018 | The system shall present a results summary with a lyrics preview and a button to open the output folder. | P2 | Given a completed run, When results show, Then a lyrics preview and an "open folder" action are available. | US-1 |

---

## 9. Non-Functional Requirements

| ID      | Category        | Requirement                                                                                      | Priority |
| ------- | --------------- | ----------------------------------------------------------------------------------------------- | -------- |
| NFR-001 | Performance     | Target ≤ 5 min end-to-end for a 3–4 min song on the Ryzen 7 4800H CPU; treated as a **soft** target — output quality takes precedence (NFR-010), so the transcription path may run longer when higher-accuracy options are enabled. `[CONFIRMED]` | P1 |
| NFR-002 | Usability       | Single-screen interface; starting a job takes ≤ 2 interactions (paste, click).                   | P0 |
| NFR-003 | Reliability     | Partial-failure isolation: a failure in one stage never discards already-produced outputs.        | P1 |
| NFR-004 | Portability     | Runs locally on Windows 11 (the user's machine); Windows 10 likely compatible. `[CONFIRMED]`     | P0 |
| NFR-005 | Privacy/Offline | No paid cloud services; the only network calls are the YouTube download and the lyrics lookup. Transcription runs locally. `[CONFIRMED]` | P0 |
| NFR-006 | Resource use    | Model + processing fit within 16 GB RAM; models/outputs fit the available 50 GB+ disk. `[CONFIRMED]` | P1 |
| NFR-007 | Maintainability | Dependencies pinned/documented; yt-dlp updatable independently when YouTube changes.               | P1 |
| NFR-008 | Accuracy        | Lyrics line-alignment meets the §3 target for clearly-sung English vocals (synced path; best-effort + forced alignment / vocal isolation on the transcription path). | P0 |
| NFR-009 | i18n / l10n     | N/A — English-only scope; interface in English. `[CONFIRMED]`                                     | P2 |
| NFR-010 | Quality vs speed | Output quality takes precedence over processing speed; when they conflict, prefer the more accurate option. `[CONFIRMED]` | P0 |

---

## 10. Technical Considerations, Dependencies & Constraints

**Constraints.**

- Runs locally on Windows on the user's hardware: AMD Radeon RX5500M GPU, AMD Ryzen 7 4800H CPU (8 cores / 16 threads). `[CONFIRMED]`
- **Compute: CPU-only (decided).** The RX5500M is an AMD GPU; WhisperX / faster-whisper run on CTranslate2, which GPU-accelerates only on NVIDIA CUDA — so the GPU cannot accelerate them. Transcription runs on the Ryzen 7 4800H CPU (CTranslate2 int8). GPU acceleration is not pursued: the only AMD path (whisper.cpp + Vulkan) gives less precise timing than WhisperX forced alignment. `[CONFIRMED]`
- **Processing-time consequence.** large-v3 + Demucs on CPU is slow — expect the transcription fallback to take roughly ~10–30 min for a 4-min song. This is an accepted tradeoff (quality > speed, NFR-010); the ≤5 min figure is a soft target. The synced-lyrics path stays near-instant, so maximizing synced-source coverage minimizes how often the slow path runs. `[CONFIRMED]`
- Free/open tooling only; no paid APIs. `[CONFIRMED]`
- **Decided processing stack.** yt-dlp (download + metadata) → ffmpeg (320 kbps MP3) → multi-source synced-lyrics search (LRCLIB + others) → on miss, Demucs vocal isolation + WhisperX (large-v3, CPU/int8) with VAD + forced alignment → write 4 lyrics formats; Streamlit UI. `[CONFIRMED]`

**Dependencies.**

| Dependency            | Type        | Owner | Status |
| --------------------- | ----------- | ----- | ------ |
| yt-dlp (audio download + metadata) | external / OSS | upstream | `[CONFIRMED]` |
| ffmpeg (320 kbps MP3 transcode)    | external / OSS | upstream | `[CONFIRMED]` |
| Synced lyrics — multi-source (LRCLIB + others, e.g. `syncedlyrics` aggregator: NetEase/Musixmatch/Megalobiz) | external API | upstream | `[CONFIRMED]` |
| WhisperX (large-v3, CPU/int8) — transcription + forced alignment + VAD | external / OSS | upstream | `[CONFIRMED]` |
| Demucs — vocal isolation before transcription | external / OSS | upstream | `[CONFIRMED]` |
| GUI: Streamlit (local web app) | external / OSS | upstream | `[CONFIRMED]` |
| Python runtime + `.bat` launcher (venv) | platform | self | `[CONFIRMED]` |

**APIs & integrations.** YouTube (via yt-dlp). Synced-lyrics lookup across multiple free providers (LRCLIB primary, plus others such as NetEase / Musixmatch / Megalobiz via the `syncedlyrics` aggregator) — all key-less / free. No paid services. `[CONFIRMED]`

**Data & analytics.** No database; outputs are files on local disk. No external analytics/telemetry (local personal tool). A local per-run log captures the §3 metrics that can be measured automatically — lyrics source (synced vs transcribed → synced-hit-rate), end-to-end processing time, and success/failure. The quality metrics (±0.2s alignment, manual-cleanup effort) are assessed by manual spot-check. `[CONFIRMED]`

**Design doc.** Not required for v1 — the stack and alignment approach are specified inline (this section plus §7 and §8). A short design doc may be added at build time if the implementation grows.

---

## 11. Release & Rollout Plan

**Milestones / phases**

| Phase | Scope (requirement IDs) | Target | Exit criteria |
| ----- | ----------------------- | ------ | ------------- |
| M1 — Synced-lyrics happy path (Streamlit) | FR-001, FR-003, FR-004, FR-005, FR-007, FR-009, FR-010, FR-012, FR-015 | TBD | Paste URL → confirm metadata → when synced lyrics exist, get a 320 kbps MP3 + 4 timestamped lyric files in a "Title - Artist" folder; re-runs don't overwrite |
| M2 — Transcription fallback (quality stack) | FR-006 (WhisperX large-v3 + Demucs), FR-016, FR-008, FR-011, FR-014 | TBD | Songs without synced lyrics get locally-transcribed line-level lyrics; audio preserved on lyrics failure; non-English warns &amp; stops |
| M3 — Polish | FR-002, FR-013, FR-018, NFR-001/008 tuning | TBD | URL validation, lyrics preview + open-folder, choosable output folder, quality/perf tuning |

**Rollout strategy.** Single-user local install: a Python virtual environment plus a double-click `.bat` launcher that starts the Streamlit app. No flags or staged rollout. An optional one-click `.exe` is a possible later convenience. `[CONFIRMED]`

**Launch criteria.** v1 ships when a valid English-song URL, through the Streamlit app, reliably yields a 320 kbps MP3 and four line-level lyric files (synced when available, else WhisperX + Demucs transcription) into a per-song "Title - Artist" folder — with the metadata-confirm step, re-run safety, and audio-preserved-on-lyrics-failure all working.

**GTM coordination.** N/A — personal tool, no go-to-market.

---

## 12. Risks, Assumptions & Open Questions

**Assumptions**

- [CONFIRMED] CPU transcription with large-v3 + Demucs is slow (~10–30 min/song) and that is accepted (quality > speed, NFR-010) — the synced-lyrics path stays fast, so this only affects songs that miss.
- [ASSUMPTION] Multi-source synced-lyrics search (LRCLIB + others) covers a meaningful share of the user's songs — *accepted risk R-003; validate by: testing a sample of representative URLs.*
- [ASSUMPTION] Title/artist from the video is usually clean enough to match lyrics — *accepted risk R-006; mitigated by the metadata-confirm step (FR-015); validate by: trying messy real-world titles.*
- [CONFIRMED] Lyrics output in four line-level formats — plain text `[mm:ss]`, SRT, LRC, JSON (all emitted per run).
- [CONFIRMED] Personal-use tool; the user produces lyric videos for YouTube — publishing/licensing of those videos is the user's responsibility (R-002), not handled by the tool.

**Risks**

| ID    | Risk                                                                 | Likelihood | Impact | Mitigation |
| ----- | ------------------------------------------------------------------- | ---------- | ------ | ---------- |
| R-001 | CPU-only large-v3 + Demucs is slow (~10–30 min/song on the transcription path) | H | M | Accepted tradeoff (quality > speed, NFR-010); maximize synced-lyrics coverage to avoid the slow path; offer `medium.en` as a faster fallback if needed |
| R-002 | Legal/ToS: downloading YouTube audio and copyrighted lyrics          | M | M | Personal use only; document scope; no redistribution; user-owned decision |
| R-003 | Synced lyrics missing → falls back to the slow transcription path     | M | M | Multi-source synced search (LRCLIB + others) to raise hit rate; solid transcription fallback |
| R-004 | Transcribing sung vocals over instrumentation is less accurate than speech | M | M | Demucs vocal isolation + WhisperX forced alignment + large-v3; user confirms metadata; moderate touch-up acceptable |
| R-005 | yt-dlp breaks when YouTube changes                                    | M | M | Keep yt-dlp updatable independently; surface clear errors |
| R-006 | Wrong lyrics matched due to bad title parsing                        | M | L | Fuzzy matching; allow manual title/artist override |

**Open Questions**

| ID    | Question                                                                                  | Owner | Status | Resolution / Date |
| ----- | ---------------------------------------------------------------------------------------- | ----- | ------ | ----------------- |
| Q-001 | GUI framework: lightweight local web app (Streamlit) vs native desktop (Tkinter/PySide)? | Pranita | Answered | Streamlit local web app · 2026-06-09 |
| Q-002 | Transcription engine & model size (faster-whisper / WhisperX / whisper.cpp; tiny→medium)? | Pranita | Answered | WhisperX, large-v3, CPU/int8 · 2026-06-09 |
| Q-003 | Pursue any AMD-friendly GPU acceleration (DirectML/OpenVINO/ROCm) or accept CPU-only?      | Pranita | Answered | CPU-only; no GPU acceleration · 2026-06-09 |
| Q-004 | Exact plain-text timestamp format — `[mm:ss]` vs `[mm:ss.cs]`; any header metadata?        | Pranita | Answered | Plain text `[mm:ss]`; also SRT/LRC/JSON, line-level · 2026-06-09 |
| Q-005 | Output folder location and file-naming convention?                                         | Pranita | Answered | Per-song subfolder named "Title - Artist" · 2026-06-09 |
| Q-006 | Use vocal separation (e.g. Demucs) to improve transcription, despite the performance cost? | Pranita | Answered | Yes — Demucs on the fallback path · 2026-06-09 |
| Q-007 | How to handle a non-English song — warn, skip, or attempt anyway?                          | Pranita | Answered | Warn and stop (skip the song) · 2026-06-09 |
| Q-008 | Which lyrics source(s) — LRCLIB only or add others? Any licensing concerns?                | Pranita | Answered | Multi-source: LRCLIB + others via `syncedlyrics` · 2026-06-09 |
| Q-009 | Packaging — run as a Python script, or build a one-click `.exe`?                           | Pranita | Answered | Python script + `.bat` launcher; .exe optional later · 2026-06-09 |
| Q-010 | Concrete performance target acceptable to the user (the §3 ≤5 min guess)?                  | Pranita | Answered | 3–5 min/song acceptable; ≤5 min guardrail · 2026-06-09 |

---

## 13. Appendix, References & Glossary

**References.** Decided stack: yt-dlp (download + metadata), ffmpeg (320 kbps MP3), `syncedlyrics` aggregator + LRCLIB (multi-source synced lyrics), WhisperX (transcription + forced alignment + VAD), Demucs (vocal isolation), Streamlit (UI). A short engineering design doc for the "how" is to be written and linked from §10.

**Glossary.**

- **Synced / time-synced lyrics** — lyrics where each line carries a timestamp (the `.lrc` convention), enabling line-by-line following during playback.
- **LRC** — a lyrics file format that prefixes each line with a `[mm:ss.xx]` timestamp. One of the four output formats.
- **Transcription** — converting spoken/sung audio to text; here, locally, with per-line timing.
- **Line-level timestamps** — one timestamp per lyric line (as opposed to per word).
- **Fallback** — using local transcription when no online synced lyrics are found.
- **yt-dlp** — open-source tool for downloading audio/video and metadata from YouTube and other sites.
- **WhisperX** — transcription tool combining Whisper with voice-activity detection and forced alignment for accurate line/word timestamps.
- **Demucs** — an audio source-separation model used here to isolate vocals from the instrumental before transcription.
- **Forced alignment** — aligning recognized words to their exact audio times to produce precise timestamps.
- **VAD (voice-activity detection)** — detecting which audio spans contain voice, so silent/instrumental sections are skipped.

### Change Log
| Version | Date       | Author  | Change        |
| ------- | ---------- | ------- | ------------- |
| 0.1.0   | 2026-06-09 | Pranita | Initial draft |
| 0.2.0   | 2026-06-09 | Pranita | Clarified all sections; resolved Q-001–Q-010; decided Streamlit + WhisperX/Demucs (CPU) + multi-source synced lyrics; 4 output formats; lyric-video framing; metadata-confirm & re-run safety → P0 |
| 1.0.0   | 2026-06-09 | Pranita | Finalized; consistency pass (320 kbps wireframe fix, multi-source flow wording, ±0.2s note, format field specs, instrumentation, design-doc & comment cleanup); approved to build |
| 1.0.0   | 2026-06-09 | Pranita | Handoff generated (HANDOFF.md, TASKS.md) |
