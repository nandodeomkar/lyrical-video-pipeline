"""WhisperX worker — runs in a child process so model RAM frees on exit.

Pipeline (PRD §10 decided stack): large-v3 on CPU at int8, VAD-gated so
instrumental spans yield no lines (FR-016), then forced alignment for
line-level timestamps (FR-006). English gate first (FR-014): language is
detected on a mid-track slice of the vocals (intros are often instrumental);
non-English stops before the expensive full transcription.

Writes JSON to the given path:
  {"language": "en", "lines": [{"start": s, "end": e, "text": t}, ...]}
  {"error": "non_english", "language": "xx"}
Exit code is 0 in both cases; non-zero means the worker itself broke.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000  # whisperx.load_audio output rate
DETECT_SLICE_S = 60

# FR-016 energy gate: Whisper hallucinates short phrases ("Thank you.") over
# near-silence that VAD lets through. Since the input is the Demucs vocals
# stem, real sung lines carry energy; a line over a near-silent span is a
# hallucination. Drop lines >30 dB below the loudest line or under -50 dBFS.
REL_DB_WINDOW = 30.0
ABS_DB_FLOOR = -50.0

# Line re-segmentation: large-v3 merges whole choruses into one segment, so
# lines are rebuilt from word-level alignment. A gap >= HARD_GAP_S or
# sentence-final punctuation always starts a new line; lines still longer
# than MAX_LINE_CHARS split recursively at their largest internal word gap —
# in singing that is the phrase boundary (the breath), not a character count.
HARD_GAP_S = 0.8
MAX_LINE_CHARS = 45
_SENTENCE_END = (".", "!", "?", "…")


def _fill_missing_times(words: list[dict]) -> None:
    """Alignment occasionally leaves words untimed (digits etc.) — interpolate."""
    prev_end = 0.0
    for w in words:
        if w["start"] is None:
            w["start"] = prev_end
        if w["end"] is None:
            w["end"] = w["start"]
        prev_end = w["end"]


def _split_long(group: list[dict]) -> list[list[dict]]:
    text_len = len(" ".join(w["word"] for w in group))
    if text_len <= MAX_LINE_CHARS or len(group) < 2:
        return [group]
    gaps = [(group[j + 1]["start"] - group[j]["end"], j) for j in range(len(group) - 1)]
    _, j = max(gaps)
    return _split_long(group[: j + 1]) + _split_long(group[j + 1 :])


def split_into_lines(words: list[dict]) -> list[dict]:
    """Rebuild lyric lines from aligned words: [{'start','end','text'}, ...]."""
    if not words:
        return []
    _fill_missing_times(words)
    groups: list[list[dict]] = []
    current: list[dict] = []
    for i, w in enumerate(words):
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 0.0
        if nxt is None or gap >= HARD_GAP_S or w["word"].endswith(_SENTENCE_END):
            groups.append(current)
            current = []
    return [
        {
            "start": round(float(g[0]["start"]), 3),
            "end": round(float(g[-1]["end"]), 3),
            "text": " ".join(w["word"] for w in g).strip(),
        }
        for group in groups
        for g in _split_long(group)
        if " ".join(w["word"] for w in g).strip()
    ]


def filter_silent_lines(lines: list[dict], audio, sr: int = SAMPLE_RATE) -> list[dict]:
    if not lines:
        return lines
    dbs = []
    for ln in lines:
        span = audio[int(ln["start"] * sr) : max(int(ln["end"] * sr), int(ln["start"] * sr) + 1)]
        rms = float(np.sqrt(np.mean(np.square(span, dtype=np.float64)))) if span.size else 0.0
        dbs.append(20.0 * float(np.log10(rms)) if rms > 0 else -120.0)
    ceiling = max(dbs)
    return [
        ln
        for ln, db in zip(lines, dbs)
        if db >= ABS_DB_FLOOR and db >= ceiling - REL_DB_WINDOW
    ]


def _load_model(whisperx, name: str, device: str, compute_type: str):
    try:
        return whisperx.load_model(name, device, compute_type=compute_type)
    except Exception as first_err:  # pyannote VAD assets can be unavailable
        try:
            return whisperx.load_model(
                name, device, compute_type=compute_type, vad_method="silero"
            )
        except TypeError:  # older whisperx without vad_method kwarg
            raise first_err


def _detect_language(model, audio) -> str:
    """Detect on a slice from 25% into the track — vocals, not the intro."""
    duration = len(audio) / SAMPLE_RATE
    if duration > 2.5 * DETECT_SLICE_S:
        start = int(duration * 0.25) * SAMPLE_RATE
        sample = audio[start : start + DETECT_SLICE_S * SAMPLE_RATE]
    else:
        sample = audio
    try:
        return model.detect_language(sample)
    except AttributeError:  # older whisperx: detection only via transcribe
        return model.transcribe(sample, batch_size=4)["language"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio")
    parser.add_argument("out_json")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    args = parser.parse_args()

    import whisperx  # heavy import — deferred so argparse errors stay fast

    out = Path(args.out_json)
    audio = whisperx.load_audio(args.audio)
    model = _load_model(whisperx, args.model, args.device, args.compute_type)

    language = _detect_language(model, audio)
    if language != "en":
        out.write_text(
            json.dumps({"error": "non_english", "language": language}),
            encoding="utf-8",
        )
        return 0

    # Forcing language="en" (now confirmed) skips re-detection drift.
    result = model.transcribe(audio, language="en", batch_size=4)
    align_model, metadata = whisperx.load_align_model(language_code="en", device=args.device)
    aligned = whisperx.align(
        result["segments"], align_model, metadata, audio, args.device,
        return_char_alignments=False,
    )
    words: list[dict] = []
    for seg in aligned["segments"]:
        seg_words = seg.get("words") or []
        if not seg_words:
            # alignment failed for this segment — keep it whole as one pseudo-word
            if seg.get("text", "").strip() and seg.get("start") is not None:
                words.append(
                    {
                        "word": seg["text"].strip(),
                        "start": float(seg["start"]),
                        "end": float(seg.get("end") or seg["start"]),
                    }
                )
            continue
        for w in seg_words:
            token = str(w.get("word", "")).strip()
            if token:
                words.append({"word": token, "start": w.get("start"), "end": w.get("end")})
    lines = split_into_lines(words)
    lines = filter_silent_lines(lines, audio)
    out.write_text(
        json.dumps({"language": language, "lines": lines}, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
