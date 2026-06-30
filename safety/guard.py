import re
from actions.tts import speak

_DANGEROUS_ACTIONS = {"delete_file", "format_disk", "empty_trash"}
_DANGEROUS_KEYWORDS = re.compile(
    r"\b(delete|remove|trash|format|purchase|buy|send email|send message|empty trash)\b",
    re.IGNORECASE,
)


def _listen_for_confirmation() -> str:
    import sounddevice as sd
    import numpy as np
    import tempfile, wave, os
    from stt.macos_speech import MacOSSpeechAdapter

    sample_rate = 16000
    duration = 3
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


class SafetyGuard:
    def __init__(self, require_confirmation: bool = True):
        self._require = require_confirmation

    def is_dangerous(self, action: str, params: dict) -> bool:
        if action in _DANGEROUS_ACTIONS:
            return True
        for v in params.values():
            if isinstance(v, str) and _DANGEROUS_KEYWORDS.search(v):
                return True
        return False

    def check(self, action: str, params: dict) -> bool:
        if not self._require or not self.is_dangerous(action, params):
            return True
        speak("위험한 작업입니다. 진행할까요? 네 또는 아니오로 말씀해주세요.")
        response = _listen_for_confirmation()
        return "네" in response or "yes" in response.lower()
