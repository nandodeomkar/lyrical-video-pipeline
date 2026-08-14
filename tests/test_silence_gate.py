"""FR-016 energy gate: hallucinated lines over near-silent vocal spans are dropped."""

import numpy as np

from pipeline.transcribe_worker import SAMPLE_RATE, filter_silent_lines


def _audio_with(spans):
    """1-min mono track, silent except (start_s, end_s, amplitude) sine spans."""
    audio = np.zeros(60 * SAMPLE_RATE, dtype=np.float32)
    t = np.arange(audio.size) / SAMPLE_RATE
    for start, end, amp in spans:
        mask = (t >= start) & (t < end)
        audio[mask] = (amp * np.sin(2 * np.pi * 220 * t[mask])).astype(np.float32)
    return audio


def test_hallucination_over_silence_dropped():
    audio = _audio_with([(20.0, 25.0, 0.3)])  # real singing only at 20–25s
    lines = [
        {"start": 9.8, "end": 11.0, "text": "Thank you."},  # silence → hallucination
        {"start": 20.0, "end": 24.5, "text": "We're no strangers to love"},
    ]
    kept = filter_silent_lines(lines, audio)
    assert [ln["text"] for ln in kept] == ["We're no strangers to love"]


def test_quieter_but_real_lines_kept():
    # second line 12 dB quieter than the first — well inside the 30 dB window
    audio = _audio_with([(10.0, 14.0, 0.4), (30.0, 34.0, 0.1)])
    lines = [
        {"start": 10.0, "end": 13.9, "text": "loud line"},
        {"start": 30.0, "end": 33.9, "text": "soft line"},
    ]
    kept = filter_silent_lines(lines, audio)
    assert len(kept) == 2


def test_empty_input_passthrough():
    assert filter_silent_lines([], np.zeros(SAMPLE_RATE, dtype=np.float32)) == []
