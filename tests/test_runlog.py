"""Run instrumentation (PRD §3/§10)."""

import json

from pipeline.runlog import append_run


def test_appends_json_lines_with_timestamp(tmp_path):
    append_run(tmp_path, {"url": "u1", "lyrics_source": "synced", "success": True})
    append_run(tmp_path, {"url": "u2", "success": False})
    records = [
        json.loads(line)
        for line in (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 2
    assert records[0]["url"] == "u1"
    assert records[0]["lyrics_source"] == "synced"
    assert all("ts" in r for r in records)
