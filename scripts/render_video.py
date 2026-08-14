"""Render a lyric video for a completed song folder (M4/M5 scope extensions).

Usage:
  .venv\\Scripts\\python.exe scripts\\render_video.py "Output\\Title - Artist" [options]

Options:
  --layout panel           video + lyrics panel (M5) instead of lyrics-only;
                           fetches the source video on demand if it's missing
  --title T / --artist A   override the names parsed from the folder base
  --frames 0-120           render only a frame range (plumbing checks)
  --cpu                    software rasterizer instead of the GPU (ANGLE/D3D11)
  --concurrency N          parallel render workers (default 4 — laptop-friendly)

With no folder argument, lists the renderable song folders under Output/.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Remotion progress lines contain emoji; don't die on a cp1252 console.
sys.stdout.reconfigure(errors="replace")

from pipeline.video import (  # noqa: E402
    CONCURRENCY_DEFAULT,
    fetch_video,
    find_song_files,
    find_video_file,
    render_lyric_video,
)

OUT_ROOT = Path(__file__).resolve().parent.parent / "Output"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", help="song folder (Output/<Title - Artist>)")
    parser.add_argument("--layout", choices=("lyrics", "panel"), default="lyrics")
    parser.add_argument("--title")
    parser.add_argument("--artist")
    parser.add_argument("--frames", help='frame range like "0-120" for a short clip')
    parser.add_argument("--cpu", action="store_true", help="render without the GPU")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY_DEFAULT)
    args = parser.parse_args()

    if not args.folder:
        print("Renderable song folders:")
        found = False
        for d in sorted(OUT_ROOT.iterdir()) if OUT_ROOT.exists() else []:
            if d.is_dir():
                try:
                    base, _, _ = find_song_files(d)
                except FileNotFoundError:
                    continue
                try:
                    find_video_file(d, base)
                    note = "video on disk — both layouts ready"
                except FileNotFoundError:
                    note = "no source video yet — --layout panel will fetch it"
                print(f'  "{d}"  ({note})')
                found = True
        if not found:
            print("  (none — run a song through the app first)")
        print("\nPass one of these paths to render it.")
        return 2

    if args.layout == "panel":
        # Fetch up front so a missing video fails fast, before bundling.
        print("Ensuring the source video is on disk ...")
        print(f"   {fetch_video(Path(args.folder)).name}")

    t0 = time.perf_counter()
    out = render_lyric_video(
        Path(args.folder),
        layout=args.layout,
        title=args.title,
        artist=args.artist,
        frames=args.frames,
        gpu=not args.cpu,
        concurrency=args.concurrency,
        on_progress=lambda line: print(f"\r   {line[:90]:<90}", end="", flush=True),
    )
    print(f"\nDone in {time.perf_counter() - t0:.0f}s: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
