import base64
import json
import time
from llm.base import LLMBase
from safety.guard import SafetyGuard
from metrics.collector import MetricsCollector
from routines.detector import RoutineDetector
from agent.cache import HotCommandCache
from agent.context import ConversationContext
from agent import tools
from actions.tts import speak
from actions.applescript import run_applescript
from actions.screen import take_screenshot

MAX_ITERATIONS = 5


class Agent:
    def __init__(
        self,
        llm: LLMBase,
        guard: SafetyGuard,
        collector: MetricsCollector,
        detector: RoutineDetector,
        tts_config,
    ):
        self._llm = llm
        self._guard = guard
        self._collector = collector
        self._detector = detector
        self._tts = tts_config
        self._cache = HotCommandCache()
        self._context = ConversationContext()

    def run(self, command: str) -> str:
        start = time.monotonic()
        retry = 0

        cached = self._cache.get(command)
        if cached:
            action_str, params_str = cached.split(":", 1) if ":" in cached else (cached, "{}")
            try:
                params_dict = json.loads(params_str)
            except (json.JSONDecodeError, ValueError):
                params_dict = {}
            if action_str == "launch_app":
                import re
                _SAFE = re.compile(r'^[A-Za-z0-9 ._-]+$')
                app = params_dict.get("app", params_str)
                if not _SAFE.match(str(app)):
                    return f"error: invalid app name: {app}"
                result = run_applescript(f'tell application "{app}" to activate')
            else:
                result = tools.dispatch(action_str, params_dict)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            speak("완료했습니다.", self._tts.voice, self._tts.rate)
            self._collector.record(command, 0.99, True, 0, False, elapsed_ms, False)
            return result

        final_response = ""
        action = "none"
        params: dict = {}
        pending_vision: dict | None = None
        for i in range(MAX_ITERATIONS):
            messages = self._context.to_messages(command if i == 0 else None)
            if pending_vision:
                messages.append(pending_vision)
                pending_vision = None
            raw = self._llm.complete(messages)

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                final_response = raw
                break

            action = parsed.get("action", "speak_only")
            params = parsed.get("params", {})
            done = parsed.get("done", False)
            response_text = parsed.get("response", "")

            if not self._guard.check(action, params):
                speak("작업을 취소했습니다.", self._tts.voice, self._tts.rate)
                final_response = "취소됨"
                retry += 1
                break

            if self._guard.is_dangerous(action, params):
                retry += 1

            tools.dispatch(action, params)
            self._cache.record(command, f"{action}:{json.dumps(params)}")

            if done:
                final_response = response_text
                break

            # Vision-verify: feed screenshot back so LLM can confirm success
            if action != "speak_only" and i < MAX_ITERATIONS - 1:
                try:
                    img_b64 = base64.b64encode(take_screenshot()).decode()
                    pending_vision = {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                            {"type": "text", "text": "화면 상태입니다. 작업이 완료됐는지 확인하고 계속하세요."},
                        ],
                    }
                except Exception:
                    pass

        elapsed_ms = int((time.monotonic() - start) * 1000)
        success = bool(final_response and final_response != "취소됨")
        is_repeated = self._detector.record(command)
        self._context.add_turn(command, final_response)
        self._collector.record(command, 0.95, success, retry,
                               self._guard.is_dangerous(action, params),
                               elapsed_ms, is_repeated)

        if final_response:
            speak(final_response, self._tts.voice, self._tts.rate)
        if is_repeated:
            speak("이 명령을 루틴으로 저장할까요?", self._tts.voice, self._tts.rate)

        return final_response
