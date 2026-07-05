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


# Shared with the proactive-suggestion flow; the alias keeps this module's
# patch seam (`safety.guard._listen_for_confirmation`) intact for tests.
from stt.confirm import listen_for_confirmation as _listen_for_confirmation


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
