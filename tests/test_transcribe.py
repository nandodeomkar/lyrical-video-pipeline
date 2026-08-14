"""Worker-output parsing for the transcription fallback (FR-006/011/014). Offline."""

import pytest

from pipeline.transcribe import NonEnglishError, TranscriptionError, parse_worker_output


def test_lines_parsed_sorted_and_cleaned():
    lines = parse_worker_output(
        {"language": "en", "lines": [
            {"start": 30.0, "end": 33.0, "text": " second "},
            {"start": 12.5, "end": 15.0, "text": "first"},
            {"start": 20.0, "end": 21.0, "text": "   "},  # VAD residue → dropped
        ]}
    )
    assert [(ln.start, ln.text) for ln in lines] == [(12.5, "first"), (30.0, "second")]


def test_non_english_raises_with_language():
    with pytest.raises(NonEnglishError) as exc:
        parse_worker_output({"error": "non_english", "language": "es"})
    assert exc.value.language == "es"


def test_missing_lines_is_transcription_error():
    with pytest.raises(TranscriptionError):
        parse_worker_output({"error": "boom"})


def test_no_usable_lines_is_transcription_error():
    with pytest.raises(TranscriptionError):
        parse_worker_output({"language": "en", "lines": [{"start": 1, "end": 2, "text": "  "}]})
