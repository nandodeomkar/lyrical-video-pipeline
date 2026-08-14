"""Stage 5 — transcription fallback orchestration (FR-006, FR-014, FR-016).

Demucs and WhisperX each run in a child process (Demucs via its own CLI,
WhisperX via pipeline.transcribe_worker) so their multi-GB model memory is
fully released between stages and between songs — the Streamlit parent stays
small (NFR-006: 16 GB budget).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .lyrics import LyricLine

DEMUCS_MODEL = "htdemucs"
WHISPER_MODEL = "large-v3"  # PRD §10 decided stack; quality > speed (NFR-010)


class TranscriptionError(RuntimeError):
    """Transcription failed; the MP3 must still be kept (FR-011)."""


class NonEnglishError(RuntimeError):
    """Detected non-English vocals — warn and stop, no lyrics (FR-014)."""

    def __init__(self, language: str):
        super().__init__(f"detected non-English audio: {language!r}")
        self.language = language


def _python() -> str:
    return sys.executable


def isolate_vocals(audio: Path, work_dir: Path) -> Path:
    """Run Demucs two-stem separation; return the vocals wav (FR-006 part)."""
    out_dir = work_dir / "demucs"
    cmd = [
        _python(), "-m", "demucs.separate",
        "--two-stems", "vocals",
        "-n", DEMUCS_MODEL,
        "-d", "cpu",
        "-o", str(out_dir),
        str(audio),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    vocals = out_dir / DEMUCS_MODEL / audio.stem / "vocals.wav"
    if proc.returncode != 0 or not vocals.exists():
        raise TranscriptionError(
            f"Demucs vocal isolation failed (exit {proc.returncode}):\n"
            f"{(proc.stderr or '')[-2000:]}"
        )
    return vocals


def parse_worker_output(payload: dict) -> list[LyricLine]:
    """Map worker JSON to clean, sorted LyricLines (pure; unit-tested)."""
    if payload.get("error") == "non_english":
        raise NonEnglishError(payload.get("language", "unknown"))
    if "lines" not in payload:
        raise TranscriptionError(f"worker returned no lines: {payload.get('error', 'unknown error')}")
    lines = [
        LyricLine(start=float(item["start"]), text=str(item["text"]).strip())
        for item in payload["lines"]
        if str(item.get("text", "")).strip()
    ]
    lines.sort(key=lambda ln: ln.start)
    if not lines:
        raise TranscriptionError("transcription produced no usable lines")
    return lines


def transcribe_aligned(vocals: Path, work_dir: Path, model: str = WHISPER_MODEL) -> list[LyricLine]:
    """Run the WhisperX worker (VAD + forced alignment); return timed lines.

    Raises NonEnglishError (FR-014) or TranscriptionError (FR-011 path).
    """
    out_json = work_dir / "transcription.json"
    cmd = [
        _python(), "-m", "pipeline.transcribe_worker",
        str(vocals), str(out_json),
        "--model", model,
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if proc.returncode != 0 or not out_json.exists():
        raise TranscriptionError(
            f"WhisperX worker failed (exit {proc.returncode}):\n{(proc.stderr or '')[-2000:]}"
        )
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    return parse_worker_output(payload)
