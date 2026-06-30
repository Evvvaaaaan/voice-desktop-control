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
                app = params_dict.get("app", params_str)
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
        for i in range(MAX_ITERATIONS):
            messages = self._context.to_messages(command if i == 0 else None)
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
