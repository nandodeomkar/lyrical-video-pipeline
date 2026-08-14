"""Per-run instrumentation (PRD §3 metrics, §10 data): JSON Lines log.

Each run appends one record capturing lyrics source (synced hit rate),
processing time, and success/failure — the automatically measurable metrics.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def append_run(log_dir: Path, record: dict) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    full = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **record}
    with (log_dir / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(full, ensure_ascii=False) + "\n")
