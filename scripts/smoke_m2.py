"""Live smoke for the M2 transcription fallback (FR-006/014/016).

Downloads real audio, trims it (bounds CPU time), then runs the actual
Demucs → WhisperX chain via the pipeline modules. English mode checks that
the instrumental intro produces no hallucinated lines (FR-016) and that the
first line lands near the known synced-lyrics timing. --non-english checks
the FR-014 gate stops before transcribing.

Usage:
  .venv\\Scripts\\python.exe scripts\\smoke_m2.py [--model large-v3] [--trim 95]
  .venv\\Scripts\\python.exe scripts\\smoke_m2.py --non-english

Temp-dir only; self-cleaning. Expect minutes of CPU time with large-v3.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.download import download_audio
from pipeline.formats import write_all
from pipeline.transcribe import NonEnglishError, isolate_vocals, transcribe_aligned

ENGLISH_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Never Gonna Give You Up
NON_ENGLISH_URL = "https://www.youtube.com/watch?v=kJQP7kiw5Fk"  # Despacito (Spanish)
# Synced-lyrics reference for the English track: first sung line at ~18.9s
FIRST_LINE_REF_S = 18.9
INTRO_GUARD_S = 14.0  # any line before this is a hallucinated-intro failure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--trim", type=int, default=95)
    parser.add_argument("--non-english", action="store_true")
    args = parser.parse_args()
    url = args.url or (NON_ENGLISH_URL if args.non_english else ENGLISH_URL)

    work = Path(tempfile.mkdtemp(prefix="smoke-m2-"))
    failures: list[str] = []
    try:
        t0 = time.perf_counter()
        print(f"1) Downloading {url} ...")
        dl = download_audio(url, work)
        print(f"   {dl.title!r} / {dl.artist!r} ({dl.duration:.0f}s)")

        print(f"2) Trimming to {args.trim}s ...")
        trimmed = work / "trimmed.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(dl.audio_path), "-t", str(args.trim),
             "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(trimmed)],
            capture_output=True, check=True,
        )

        print("3) Demucs vocal isolation ...")
        t1 = time.perf_counter()
        vocals = isolate_vocals(trimmed, work)
        print(f"   vocals.wav ready ({time.perf_counter() - t1:.0f}s)")

        print(f"4) WhisperX transcription ({args.model}, cpu/int8) ...")
        t2 = time.perf_counter()
        try:
            lines = transcribe_aligned(vocals, work, model=args.model)
        except NonEnglishError as exc:
            if args.non_english:
                print(f"   gate fired: language={exc.language!r} "
                      f"({time.perf_counter() - t2:.0f}s)")
                print("\nSMOKE PASSED — FR-014 non-English warn-and-stop verified.")
                return 0
            raise
        if args.non_english:
            failures.append("FR-014: non-English track was transcribed instead of stopped")
            lines = []
        else:
            print(f"   {len(lines)} lines ({time.perf_counter() - t2:.0f}s)")
            for ln in lines[:5]:
                print(f"   [{ln.start:6.2f}] {ln.text}")

        if lines:
            starts = [ln.start for ln in lines]
            if starts != sorted(starts):
                failures.append("FR-006: line starts not monotonically sorted")
            if len(lines) < 5:
                failures.append(f"FR-006: too few lines ({len(lines)})")
            if starts and starts[0] < INTRO_GUARD_S:
                failures.append(
                    f"FR-016: line at {starts[0]:.2f}s inside the instrumental intro"
                )
            if starts and abs(starts[0] - FIRST_LINE_REF_S) > 3.0:
                failures.append(
                    f"alignment: first line {starts[0]:.2f}s vs synced ref {FIRST_LINE_REF_S}s"
                )
            too_long = [ln for ln in lines if len(ln.text) > 60]
            if too_long:
                failures.append(
                    f"line splitting: {len(too_long)} line(s) over 60 chars, "
                    f"e.g. {too_long[0].text[:70]!r}"
                )
            print("5) Writing the four formats from transcribed lines ...")
            paths = write_all(lines, float(args.trim), work / "out", "Smoke - Test")
            missing = [e for e, p in paths.items() if not (p.exists() and p.stat().st_size)]
            if missing:
                failures.append(f"FR-007 integration: missing outputs {missing}")

        print(f"\nTotal: {time.perf_counter() - t0:.0f}s")
        if failures:
            print("SMOKE FAILED:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("SMOKE PASSED — transcription fallback verified.")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
