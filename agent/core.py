import json
import re
import time
from urllib.parse import unquote
from llm.base import LLMBase
from safety.guard import SafetyGuard
from metrics.collector import MetricsCollector
from routines.detector import RoutineDetector
from agent.cache import HotCommandCache
from agent.context import ConversationContext
from agent import tools
from actions.tts import speak
from actions.applescript import run_applescript
from actions.screen import take_screenshot_with_grid
from stt.confirm import listen_for_confirmation, parse_yes_no

# Computer-use tasks need room to screenshot → click → verify → correct.
MAX_ITERATIONS = 8

# These require seeing the screen to pick a meaningful (x, y) — without a
# screenshot the model is just guessing coordinates. scroll is exempt: x/y
# are optional there (defaults to the current pointer position), so it works
# fine blind (e.g. "scroll down").
_VISION_ONLY_ACTIONS = {"click", "double_click", "move_mouse"}

# Reasoning models (e.g. DeepSeek-style) prepend a chain-of-thought block
# before the actual answer. Cap how many times we ask one to reformat as
# JSON before giving up, so a model that never complies can't burn the
# whole iteration budget on retries alone.
MAX_JSON_RETRIES = 2

_THINK_BLOCK_RE = re.compile(r'<think>.*?</think>', re.DOTALL)


def _strip_think(raw: str) -> str:
    """Strip a leading <think>...</think> reasoning block from an LLM response.

    Some hosted reasoning models (observed with NVIDIA NIM's deepseek-v4-pro)
    start the assistant turn already inside "thinking" mode via their chat
    template, so the returned text has no opening <think> — only reasoning
    prose followed by a stray closing </think>. Handle both shapes.
    """
    cleaned = _THINK_BLOCK_RE.sub("", raw)
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1]
    return cleaned


_PERCENT_ENCODED_RUN_RE = re.compile(r'(?:%[0-9A-Fa-f]{2}){3,}')


def _decode_stray_percent_encoding(text: str) -> str:
    """Some models copy a URL's percent-encoded query straight into the
    spoken "response" instead of writing natural language, which TTS then
    reads out character by character (e.g. "퍼센트 이디..."). Runs of 3+
    %XX groups are decoded back to the original text; a stray "%" in normal
    prose (e.g. "50% 할인") never matches this pattern."""
    return _PERCENT_ENCODED_RUN_RE.sub(
        lambda m: unquote(m.group(0)), text
    )


class Agent:
    def __init__(
        self,
        llm: LLMBase,
        guard: SafetyGuard,
        collector: MetricsCollector,
        detector: RoutineDetector,
        tts_config,
        on_state=None,
        memory=None,
        retriever=None,
        routines=None,
        listen_confirm=None,
    ):
        self._llm = llm
        self._guard = guard
        self._collector = collector
        self._detector = detector
        self._tts = tts_config
        self._on_state = on_state
        self._memory = memory
        self._retriever = retriever
        self._routines = routines
        self._listen_confirm = listen_confirm or listen_for_confirmation
        self._cache = HotCommandCache()
        self._context = ConversationContext()

    def _set_state(self, state: str) -> None:
        if self._on_state:
            try:
                self._on_state(state)
            except Exception:
                pass

    def set_llm(self, llm: LLMBase) -> None:
        self._llm = llm

    def set_retriever(self, retriever) -> None:
        self._retriever = retriever

    def _log_action(self, command: str, action: str, params: dict,
                    dispatch_res: str) -> None:
        """Tier-2 behavior log; must never break the command loop."""
        if self._memory is None:
            return
        try:
            if action in ("click", "double_click", "move_mouse"):
                target = f"{params.get('x')},{params.get('y')}"
            elif action == "type_text":
                target = str(params.get("text") or "")
            else:
                target = str(params.get("app") or params.get("url")
                             or params.get("key") or params.get("name") or "")
            self._memory.log_action(
                command, action, target,
                not (isinstance(dispatch_res, str) and dispatch_res.startswith("error")),
                json.dumps(params, ensure_ascii=False)[:500],
            )
        except Exception as e:
            import sys
            print(f"[Memory] log_action failed: {e}", file=sys.stderr)

    def _log_outcome(self, command: str, success: bool, elapsed_ms: int,
                     final_response: str | None = None) -> None:
        """Tier-2 command/conversation log; must never break the command loop."""
        if self._memory is None:
            return
        try:
            self._memory.log_command(command, success, elapsed_ms)
            if final_response is not None:
                self._memory.log_conversation(command, final_response)
        except Exception as e:
            import sys
            print(f"[Memory] log_outcome failed: {e}", file=sys.stderr)

    def _observe(self, action: str, dispatch_res: str) -> dict:
        """Build the post-action observation message fed back into the loop."""
        try:
            front = run_applescript(
                'tell application "System Events" to get name of first process whose frontmost is true'
            )
        except Exception:
            front = ""
        text = (
            f"관찰: 직전 동작 '{action}'의 결과는 '{dispatch_res}'입니다. "
            f"현재 활성 앱: {front or '알 수 없음'}. "
            "요청이 완전히 끝났으면 done=true로, 아니면 다음 단계를 수행하세요."
        )
        if getattr(self._llm, "supports_vision", False) is True:
            try:
                return self._llm.build_observation(text, take_screenshot_with_grid())
            except Exception:
                pass
        return {"role": "user", "content": text}

    def run(self, command: str) -> str:
        start = time.monotonic()
        retry = 0

        cached = self._cache.get(command)
        if cached:
            import sys
            print(f"[Agent] Cache HIT for command '{command}': {cached}", file=sys.stderr)
            action_str, params_str = cached.split(":", 1) if ":" in cached else (cached, "{}")
            try:
                params_dict = json.loads(params_str)
            except (json.JSONDecodeError, ValueError):
                params_dict = {}
            if action_str == "launch_app":
                _SAFE = re.compile(r'^[A-Za-z0-9가-힣 ._-]+$')
                app = params_dict.get("app", params_dict.get("app_name", params_dict.get("name", params_str)))
                if not _SAFE.match(str(app)):
                    print(f"[Agent] Cached launch_app blocked: Invalid app name '{app}'", file=sys.stderr)
                    return f"error: invalid app name: {app}"
                print(f"[Agent] Executing cached launch_app for '{app}'...", file=sys.stderr)
                result = run_applescript(f'tell application "{app}" to activate')
            else:
                print(f"[Agent] Executing cached action '{action_str}' with {params_dict}...", file=sys.stderr)
                result = tools.dispatch(action_str, params_dict)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            failed = isinstance(result, str) and result.startswith("error")
            self._log_action(command, action_str, params_dict, result)
            self._log_outcome(command, not failed, elapsed_ms)
            self._set_state("error" if failed else "success")
            if failed:
                speak("저장된 명령 실행에 실패했어요.", self._tts.voice, self._tts.rate)
            else:
                speak("완료했습니다.", self._tts.voice, self._tts.rate)
            self._collector.record(command, 0.99, not failed, 0, False, elapsed_ms, False)
            print(f"[Agent] Cache execution finished. Result: {result}", file=sys.stderr)
            return result

        final_response = ""
        action = "none"
        params: dict = {}
        last_dispatch = ""
        json_retries = 0
        # This run's successful real actions, in order — the replayable steps
        # a saved routine would consist of.
        executed_steps: list[dict] = []
        had_dangerous = False
        # Maintain one running message list so each step remembers the original
        # command and the assistant's prior actions/observations.
        memory_block = None
        if self._retriever:
            try:
                memory_block = self._retriever.build_memory_block(command)
            except Exception as e:
                import sys
                print(f"[Memory] retrieval failed: {e}", file=sys.stderr)
        messages = self._context.to_messages(command, memory_block=memory_block)
        for i in range(MAX_ITERATIONS):
            try:
                raw = self._llm.complete(messages)
            except Exception as e:
                import sys
                print(f"[Agent] LLM call FAILED: {type(e).__name__}: {e}", file=sys.stderr)
                if "Connection" in type(e).__name__ or "Connection" in str(e):
                    final_response = "오류: LLM 서버에 연결할 수 없어요. 설정에서 LLM 상태를 확인해 주세요."
                else:
                    final_response = "오류: 명령을 처리하지 못했어요. LLM 설정을 확인해 주세요."
                break

            # Clean up markdown code blocks or leading/trailing text from LLM response
            import sys
            raw_clean = _strip_think(raw).strip()
            print(f"[Agent] Raw response received from LLM:\n{raw}\n-----------------", file=sys.stderr)
            if raw_clean.startswith("```"):
                lines = raw_clean.split("\n")
                if len(lines) >= 2 and lines[0].startswith("```"):
                    if lines[-1].strip() == "```":
                        raw_clean = "\n".join(lines[1:-1])
                    else:
                        raw_clean = "\n".join(lines[1:])
            # Extract JSON brackets if LLM added explanations outside the JSON
            json_match = re.search(r'\{.*\}', raw_clean, re.DOTALL)
            if json_match:
                raw_clean = json_match.group(0)

            print(f"[Agent] Cleaned response for JSON parsing:\n{raw_clean}\n-----------------", file=sys.stderr)
            try:
                parsed = json.loads(raw_clean)
            except json.JSONDecodeError as e:
                print(f"[Agent] JSON parsing FAILED. Error: {e}", file=sys.stderr)
                print(f"[Agent] Raw output was: {raw}", file=sys.stderr)
                if json_retries < MAX_JSON_RETRIES and i < MAX_ITERATIONS - 1:
                    json_retries += 1
                    print(f"[Agent] Asking model to reformat as JSON (retry {json_retries}/{MAX_JSON_RETRIES})...", file=sys.stderr)
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({
                        "role": "user",
                        "content": "방금 응답은 유효한 JSON이 아니었어요. 다른 설명 없이 지정된 형식의 JSON 객체 하나만 응답하세요.",
                    })
                    continue
                # The model never produced usable JSON — speaking the raw text
                # would read reasoning/prose (and stray tags) aloud, so use the
                # same honest fallback as an exhausted iteration budget instead.
                final_response = "오류: 응답 형식을 이해하지 못했어요. 다시 말씀해 주세요."
                break

            # Remember what the assistant just decided so later steps have context.
            messages.append({"role": "assistant", "content": raw})

            action = parsed.get("action", "speak_only")
            params = parsed.get("params", {})
            done = parsed.get("done", False)
            response_text = _decode_stray_percent_encoding(parsed.get("response", ""))
            print(f"[Agent] Parsed: Action='{action}', Params={params}, Done={done}, Response='{response_text}'", file=sys.stderr)

            dangerous = self._guard.is_dangerous(action, params)
            if dangerous:
                print(f"[Agent] Action flagged as DANGEROUS: {action}", file=sys.stderr)
                self._set_state("danger_confirm")
                had_dangerous = True
                retry += 1

            if not self._guard.check(action, params):
                print(f"[Agent] Action BLOCKED by Safety Guard: {action} with {params}", file=sys.stderr)
                speak("작업을 취소했습니다.", self._tts.voice, self._tts.rate)
                final_response = "취소됨"
                break

            if dangerous:
                self._set_state("executing")

            if action in _VISION_ONLY_ACTIONS and not getattr(self._llm, "supports_vision", False):
                # Without a screenshot this model has no way to know what's
                # on screen — the "0..1000 grid" coordinates it just supplied
                # are pure guesses (observed with Ollama/llama3: it "clicked
                # the left edge" and "moved to the top edge" of nothing in
                # particular, then claimed done). Reject before ever moving
                # the real mouse, and let the model try a non-visual approach.
                dispatch_res = (
                    f"error: {action} requires a vision-capable LLM provider "
                    "(screenshots aren't available with this one) — use "
                    "keyboard shortcuts, AppleScript, launch_app/open_url "
                    "instead, or tell the user honestly that this needs a "
                    "vision-capable provider (Claude/OpenAI)."
                )
                print(f"[Agent] Blocked '{action}': current LLM has no vision support", file=sys.stderr)
            else:
                print(f"[Agent] Dispatching action '{action}' with {params}...", file=sys.stderr)
                dispatch_res = tools.dispatch(action, params)
            last_dispatch = dispatch_res
            print(f"[Agent] Dispatch result: '{dispatch_res}'", file=sys.stderr)
            self._log_action(command, action, params, dispatch_res)
            if action != "speak_only" and not dispatch_res.startswith("error"):
                executed_steps.append({"action": action, "params": params})

            if done:
                if dispatch_res.startswith("error"):
                    # Harness gate (verify before done): an action that just
                    # failed cannot claim completion. Reject done=true and fall
                    # through to the observation so the model can correct
                    # itself or report the failure honestly.
                    print(f"[Agent] done=true REJECTED: last action failed ('{dispatch_res}')", file=sys.stderr)
                else:
                    # Only single-step, real actions are safe to cache: a
                    # multi-step command can't be replayed from one action and
                    # a speak_only reply would lose its answer on replay.
                    if i == 0 and action != "speak_only":
                        self._cache.record(command, f"{action}:{json.dumps(params)}")
                    final_response = response_text
                    break

            # Feed an observation of the current state back so the LLM can
            # verify success and continue. Vision-capable providers get a
            # screenshot; others get a text-only observation.
            if action != "speak_only" and i < MAX_ITERATIONS - 1:
                messages.append(self._observe(action, dispatch_res))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        success = bool(
            final_response
            and final_response != "취소됨"
            and not final_response.startswith("오류")
            and not last_dispatch.startswith("error")
        )
        # The loop ran out of steps before the model set done=true (a long or
        # under-specified command). Without this the user would hear silence,
        # which reads as "no response". Give spoken feedback instead.
        if not final_response:
            final_response = "오류: 명령을 끝까지 완료하지 못했어요. 좀 더 구체적으로 다시 말씀해 주세요."
            print("[Agent] Loop ended without a final response; using fallback.", file=sys.stderr)

        is_repeated = self._detector.record(command)
        self._context.add_turn(command, final_response)
        self._log_outcome(command, success, elapsed_ms, final_response)
        self._collector.record(command, 0.95, success, retry,
                               self._guard.is_dangerous(action, params),
                               elapsed_ms, is_repeated)

        # speak() blocks until the audio finishes playing (can be several
        # seconds for a long response, longer still when NVIDIA TTS fails and
        # falls back to local voice). Tell the HUD the outcome BEFORE that
        # call so it shows success/error immediately instead of sitting on
        # "명령 수행 중..." for the entire time the response is being read
        # aloud — otherwise a long spoken reply looks exactly like a hang.
        self._set_state("success" if success else "error")

        if final_response:
            speak(final_response, self._tts.voice, self._tts.rate)
        # Only offer what can actually be replayed: the run must have
        # succeeded with at least one real step, and none of them dangerous —
        # run_routine replays steps straight through tools.dispatch, without
        # the SafetyGuard confirmation this run went through.
        if (is_repeated and success and executed_steps and not had_dangerous
                and self._routines is not None):
            self._offer_routine_save(command, executed_steps)

        return final_response

    def _offer_routine_save(self, command: str, steps: list[dict]) -> None:
        """Voice yes/no → persist this run's steps as a replayable routine
        (listed in the HUD pinned panel, runnable via run_routine). Failures
        here must never break the command that just succeeded; silence or an
        unclear answer simply skips saving."""
        import sys
        try:
            speak("이 명령을 루틴으로 저장할까요?", self._tts.voice, self._tts.rate)
            answer = parse_yes_no(self._listen_confirm())
            if answer is True:
                self._routines.save(command, steps)
                speak("루틴으로 저장했어요.", self._tts.voice, self._tts.rate)
            elif answer is False:
                speak("알겠어요.", self._tts.voice, self._tts.rate)
        except Exception as e:
            print(f"[Agent] routine-save offer failed: {e}", file=sys.stderr)
