import re

# Decline is checked FIRST: "아니요, 됐네요" contains "네".
_DECLINE_WORDS = ("아니", "안 해", "안해", "안 돼", "안돼", "싫", "괜찮",
                  "하지 마", "하지마", "나중에", "됐", "no")
_ACCEPT_WORDS = ("좋아", "해줘", "해 줘", "오케이", "yes", "ok")
# Single syllables false-positive as substrings of almost anything ("어" is
# also a filler that can open an unrelated sentence) — they only count as an
# exact (stripped) answer.
_ACCEPT_EXACT = ("어", "응", "예")
# "네"-family words appear as syllables inside unrelated words ("네이버",
# "그렇네요"), so they only count as the utterance's first word.
_ACCEPT_LEADING = ("네", "네네", "예", "그래", "그래요", "그럼", "좋아", "좋아요")

_WORD_SPLIT_RE = re.compile(r"[\s,.!?]+")


def parse_yes_no(text: str) -> bool | None:
    """True = accept, False = decline, None = silence/unclear.

    The shared interpretation of a spoken confirmation — used by the
    danger-confirm flow, proactive suggestions, and the routine-save offer.
    Unclear answers must map to None (callers treat that as a safe no-op),
    never to an accept."""
    cleaned = text.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if any(w in lowered for w in _DECLINE_WORDS):
        return False
    if cleaned in _ACCEPT_EXACT:
        return True
    if _WORD_SPLIT_RE.split(lowered, maxsplit=1)[0] in _ACCEPT_LEADING:
        return True
    if any(w in lowered for w in _ACCEPT_WORDS):
        return True
    return None


def listen_for_confirmation(duration: int = 3) -> str:
    """Record a short utterance and transcribe it — the shared voice yes/no
    capture used by the danger-confirm flow and proactive suggestions."""
    import sounddevice as sd
    import tempfile, wave, os
    from stt.macos_speech import MacOSSpeechAdapter

    sample_rate = 16000
    audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate,
                   channels=1, dtype="int16")
    sd.wait()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        with wave.open(f.name, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio.tobytes())
        tmp_path = f.name

    try:
        adapter = MacOSSpeechAdapter()
        with open(tmp_path, "rb") as af:
            return adapter.transcribe(af.read()).strip()
    finally:
        os.unlink(tmp_path)
