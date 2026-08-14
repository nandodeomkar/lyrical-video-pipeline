"""Live smoke for the lyric-video render stage (real Remotion, ~2 min).

1) Renders frames 0-120 (4s) of the first renderable song folder in Output/
   into a temp file and checks the result is a real H.264 MP4. Verifies the
   whole toolchain — junction, bundling, props, public dir, audio — without
   paying for a full-song render.
2) Renders the same clip of the M5 VideoPanel composition against an
   ffmpeg-generated test-pattern video in a temp song folder (no network).

Run: .venv\\Scripts\\python.exe scripts\\smoke_video.py ["Output\\Title - Artist"]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Remotion progress lines contain emoji; don't die on a cp1252 console.
sys.stdout.reconfigure(errors="replace")

from pipeline.video import find_song_files, render_lyric_video  # noqa: E402

OUT_ROOT = Path(__file__).resolve().parent.parent / "Output"


def pick_folder() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    for d in sorted(OUT_ROOT.iterdir()) if OUT_ROOT.exists() else []:
        if d.is_dir():
            try:
                find_song_files(d)
                return d
            except FileNotFoundError:
                continue
    raise SystemExit("no renderable song folder in Output/ — run a song through the app first")


def probe(path: Path) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "stream=codec_name,width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout


def check_clip(out: Path, failures: list[str], label: str) -> None:
    if out.stat().st_size < 50_000:
        failures.append(f"{label}: suspiciously small render ({out.stat().st_size} bytes)")
    p = probe(out)
    print(f"   {p.strip()}")
    if "h264" not in p:
        failures.append(f"{label}: no h264 video stream")
    if "1920,1080" not in p.replace(" ", ""):
        failures.append(f"{label}: expected 1920x1080, got: {p.strip()}")


def main() -> int:
    failures: list[str] = []
    folder = pick_folder()
    base, mp3, json_path = find_song_files(folder)

    print(f'1) Rendering frames 0-120 of "{base}" (lyrics-only) ...')
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="smoke_video_") as tmp:
        out = Path(tmp) / "clip.mp4"
        render_lyric_video(
            folder,
            frames="0-120",
            out_path=out,
            on_progress=lambda line: print(f"\r   {line[:90]:<90}", end="", flush=True),
        )
        print(f"\n   rendered in {time.perf_counter() - t0:.0f}s, {out.stat().st_size:,} bytes")
        print("2) Probing with ffprobe ...")
        check_clip(out, failures, "lyrics layout")

        print("3) Rendering the M5 video + lyrics panel against a test-pattern clip ...")
        song = Path(tmp) / "panel_song"
        song.mkdir()
        shutil.copy2(mp3, song / mp3.name)
        shutil.copy2(json_path, song / json_path.name)
        gen = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=1280x720:rate=30:duration=10",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(song / f"{base}.video.mp4")],
            capture_output=True, text=True,
        )
        if gen.returncode != 0:
            failures.append(f"panel layout: ffmpeg test clip failed: {gen.stderr.strip()[:200]}")
        else:
            out2 = Path(tmp) / "panel_clip.mp4"
            t1 = time.perf_counter()
            render_lyric_video(
                song,
                layout="panel",
                frames="0-120",
                out_path=out2,
                on_progress=lambda line: print(f"\r   {line[:90]:<90}", end="", flush=True),
            )
            print(f"\n   rendered in {time.perf_counter() - t1:.0f}s, {out2.stat().st_size:,} bytes")
            print("4) Probing with ffprobe ...")
            check_clip(out2, failures, "panel layout")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f" - {f}")
        return 1
    print("\nPASS — lyric-video render stage is healthy (both layouts).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
