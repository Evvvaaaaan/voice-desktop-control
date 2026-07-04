import re
import threading
from actions.tts import speak

# How long to wait for a yes/no (voice or HUD button) before denying.
_CONFIRM_TIMEOUT_SEC = 10.0


class ConfirmDecision:
    """One-shot yes/no answer shared between the voice listener and HUD
    buttons — whichever resolves first wins; late resolutions are ignored."""

    def __init__(self):
        self._event = threading.Event()
        self._value = None

    def resolve(self, allow: bool) -> None:
        if not self._event.is_set():
            self._value = bool(allow)
            self._event.set()

    def wait(self, timeout: float):
        """Blocks up to `timeout`; returns True/False, or None on timeout."""
        self._event.wait(timeout)
        return self._value

_DANGEROUS_ACTIONS = {"delete_file", "format_disk", "empty_trash"}
_DANGEROUS_KEYWORDS = re.compile(
    r"\b(delete|remove|trash|format|purchase|buy|send email|send message|empty trash)\b",
    re.IGNORECASE,
)
# Korean has no word boundaries usable with \b, and AppleScript can shell out —
# match these as plain substrings. Commands/params are mostly Korean here.
_DANGEROUS_SUBSTRINGS = re.compile(
    r"(삭제|지워|지우|휴지통|비워|비우|포맷|초기화|결제|구매|송금"
    r"|do shell script|rm -|sudo )",
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
    def __init__(self, require_confirmation: bool = True, ui_confirm=None):
        """`ui_confirm`, when given, is called with a ConfirmDecision so a UI
        (the notch HUD's 실행/취소 buttons) can answer instead of voice."""
        self._require = require_confirmation
        self._ui_confirm = ui_confirm

    def is_dangerous(self, action: str, params: dict) -> bool:
        if action in _DANGEROUS_ACTIONS:
            return True
        for v in params.values():
            if isinstance(v, str) and (
                _DANGEROUS_KEYWORDS.search(v) or _DANGEROUS_SUBSTRINGS.search(v)
            ):
                return True
        return False

    def check(self, action: str, params: dict) -> bool:
        if not self._require or not self.is_dangerous(action, params):
            return True

        decision = ConfirmDecision()
        if self._ui_confirm:
            try:
                self._ui_confirm(decision)
            except Exception:
                pass
        speak("위험한 작업입니다. 진행할까요? 네 또는 아니오로 말씀해주세요.")

        def _voice():
            try:
                response = _listen_for_confirmation()
                if response:
                    decision.resolve("네" in response or "yes" in response.lower())
            except Exception:
                pass

        threading.Thread(target=_voice, daemon=True).start()
        # None (nobody answered in time) counts as a deny.
        return decision.wait(_CONFIRM_TIMEOUT_SEC) is True
