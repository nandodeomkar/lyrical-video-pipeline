"""Headless M1 happy-path smoke run against real services.

Exercises FR-003/004/005/007/009/012 end to end: downloads a real YouTube
URL, transcodes to 320 kbps MP3 (verified with ffprobe), searches synced
lyrics, writes the per-song output folder, then re-plans to prove collision
versioning. Writes only to temp dirs; cleans up after itself.

Usage: .venv\\Scripts\\python.exe scripts\\smoke_m1.py [URL "Title" "Artist"]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.download import download_audio
from pipeline.formats import write_all
from pipeline.lyrics import parse_lrc, search_synced
from pipeline.outputs import place_mp3, plan_output
from pipeline.transcode import transcode_to_mp3

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
FORCE_TITLE = sys.argv[2] if len(sys.argv) > 2 else None
FORCE_ARTIST = sys.argv[3] if len(sys.argv) > 3 else None


def mp3_bitrate(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=bit_rate",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return int(out)


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="smoke-work-"))
    out_root = Path(tempfile.mkdtemp(prefix="smoke-out-"))
    failures: list[str] = []
    try:
        t0 = time.perf_counter()
        print(f"1) Downloading {URL} ...")
        dl = download_audio(URL, work)
        print(f"   title={dl.title!r} artist={dl.artist!r} duration={dl.duration:.0f}s")
        print(f"   file={dl.audio_path.name} ({dl.audio_path.stat().st_size // 1024} KiB)")
        if not dl.title or dl.duration <= 0:
            failures.append("FR-003: missing title or duration")

        print("2) Transcoding to 320 kbps MP3 ...")
        mp3 = transcode_to_mp3(dl.audio_path, work / "song.mp3")
        rate = mp3_bitrate(mp3)
        print(f"   bitrate={rate} bps")
        if abs(rate - 320_000) > 2_000:
            failures.append(f"FR-004: bitrate {rate} != 320k")

        title = FORCE_TITLE or dl.title
        artist = FORCE_ARTIST or dl.artist
        print(f"3) Searching synced lyrics for {title!r} / {artist!r} ...")
        lrc = search_synced(title, artist, dl.duration)
        if not lrc:
            failures.append("FR-005: no synced lyrics found (expected a hit for this URL)")
            lines = []
        else:
            lines = parse_lrc(lrc)
            print(f"   got {len(lines)} timed lines; first: [{lines[0].start:.2f}] {lines[0].text!r}")
            if len(lines) < 10:
                failures.append(f"FR-005: suspiciously few lines ({len(lines)})")

        print("4) Writing outputs ...")
        plan = plan_output(out_root, title, artist)
        mp3_final = place_mp3(plan, mp3)
        files = [mp3_final]
        if lines:
            files += list(write_all(lines, dl.duration, plan.folder, plan.base).values())
        for f in files:
            ok = f.exists() and f.stat().st_size > 0
            print(f"   {'OK ' if ok else 'MISSING'} {f.name}")
            if not ok:
                failures.append(f"FR-007/009: bad output {f.name}")
        if plan.versioned:
            failures.append("FR-009: fresh run should not be versioned")

        print("5) Re-planning same song (collision) ...")
        plan2 = plan_output(out_root, title, artist)
        print(f"   base={plan2.base!r} versioned={plan2.versioned}")
        if not (plan2.versioned and plan2.base.endswith("(2)")):
            failures.append("FR-012: collision did not version to (2)")

        print(f"\nTotal active time: {time.perf_counter() - t0:.1f}s")
        if failures:
            print("SMOKE FAILED:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("SMOKE PASSED — full M1 happy path verified.")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(out_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
