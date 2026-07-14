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
from agent.fast_path import parse_fast_path
from agent import tools
from actions.tts import speak
from actions.applescript import run_applescript
from actions.screen import take_screenshot_with_grid
from stt.confirm import listen_for_confirmation, parse_yes_no
from actions.accessibility import snapshot_screen, clear_target_app, release_ax_flags
from diagnostics import trace

# Computer-use tasks need room to screenshot → click → verify → correct.
# Multi-stage requests (draft a Gmail message, scaffold a project in VS Code
# and drive its terminal) chain many read/click/type steps, so the budget has
# to be generous — 8 exhausted mid-task and the model gave up honestly. Each
# step is still one LLM round-trip, so this is a ceiling, not a target.
MAX_ITERATIONS = 16

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

_SCREEN_OBSERVATION_ACTIONS = {"screenshot", "click", "double_click", "move_mouse", "scroll", "type_text"}

# Snapshot-dependent actions can't be replayed from the hot cache (the id
# refers to a screen that no longer exists), and read_screen alone does
# nothing user-visible.
_UNCACHEABLE_ACTIONS = {"speak_only", "read_screen", "click_element", "set_value"}

# Let the UI react (menu open, page transition) before re-reading elements.
_ELEMENT_SETTLE_SEC = 0.4

# Marks where an element listing starts inside an observation message. Only
# the LATEST listing is valid (ids die on every new snapshot), so when a new
# one arrives the previous message's listing is cut at this marker — keeping
# it would both bloat the prompt (up to ~150 lines per listing, resent to the
# LLM on every remaining iteration) and tempt the model into stale ids.
_ELEMENTS_MARKER = "현재 화면 요소:"
_STALE_ELEMENTS_NOTE = (
    _ELEMENTS_MARKER + " (화면이 바뀌어 이 목록은 무효화되었습니다 — 최신 목록만 사용하세요)"
)

# After launch_app / open_url the new window needs a moment to appear and
# update its title. Without this the observation grabs the PREVIOUS app's
# window title and the LLM doesn't realise the action already took effect.
_APP_SETTLE_SEC = 0.6

# Actions after which we should wait for the window to settle before observing.
_SETTLE_ACTIONS = {"launch_app", "open_url"}

_THINK_BLOCK_RE = re.compile(r'<think>.*?</think>', re.DOTALL)


def _dispatch_failed(result) -> bool:
    """Keep tool-result failure handling consistent across all agent paths."""
    return isinstance(result, str) and (
        result.startswith("error") or result == "routine_failed"
    )


def _mark_stale_elements(messages: list[dict], idx: int | None) -> None:
    """Cut the element listing out of an older observation once a newer one
    exists — its ids are unclickable by design, and every kept listing is
    re-sent to the LLM on each remaining iteration."""
    if idx is None:
        return
    content = messages[idx].get("content")
    if isinstance(content, str) and _ELEMENTS_MARKER in content:
        messages[idx]["content"] = (
            content.split(_ELEMENTS_MARKER, 1)[0] + _STALE_ELEMENTS_NOTE
        )


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
        max_iterations: int = MAX_ITERATIONS,
    ):
        self._max_iterations = max_iterations
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
        # Fingerprint of the retriever's stable memory tiers at the time the
        # current cache entries were recorded; None = not yet baselined.
        self._memory_fingerprint: str | None = None

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
        self._memory_fingerprint = None  # re-baseline on next run

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
                not _dispatch_failed(dispatch_res),
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

    @staticmethod
    def _brief_result(res: str, limit: int = 80) -> str:
        """First line only, capped: a read_screen result is a full element
        listing (up to ~150 lines), and the step summary is re-sent inside
        EVERY later observation — repeating whole listings there multiplies
        the prompt size each iteration until the LLM context overflows."""
        first, _, rest = str(res).partition("\n")
        if len(first) > limit:
            first = first[:limit] + "…"
        return first + (f" (외 {rest.count(chr(10)) + 1}줄)" if rest else "")

    @staticmethod
    def _step_summary(step_history: list[tuple[str, dict, str]]) -> str:
        """One-line-per-step summary so the LLM can see what it already did."""
        if not step_history:
            return ""
        lines = ["지금까지 수행한 단계:"]
        for idx, (act, prm, res) in enumerate(step_history, 1):
            brief = ", ".join(f"{k}={v!r}" for k, v in prm.items()) if prm else ""
            lines.append(f"  {idx}. {act}({brief}) → {Agent._brief_result(res)}")
        return "\n".join(lines)

    def _observe(self, action: str, dispatch_res: str,
                 step_history: list[tuple[str, dict, str]] | None = None) -> dict:
        """Build the post-action observation message fed back into the loop."""
        # Give the window manager a moment after navigation actions so the
        # observation reads the NEW window title, not the old one.
        if action in _SETTLE_ACTIONS and not _dispatch_failed(dispatch_res):
            time.sleep(_APP_SETTLE_SEC)

        try:
            front = run_applescript(
                'tell application "System Events" to get name of first process whose frontmost is true'
            )
        except Exception:
            front = ""

        # Try to read the active window's title — crucial after open_url /
        # launch_app so the LLM knows what page/app is now showing.
        win_title = ""
        if front:
            try:
                win_title = run_applescript(
                    f'tell application "System Events" to get name '
                    f'of front window of process "{front}"'
                ) or ""
            except Exception:
                pass

        # A successful read_screen's listing goes under _ELEMENTS_MARKER (so
        # it can be pruned once superseded), not inline in the result line.
        elements = None
        result_text = dispatch_res
        if action == "read_screen" and not _dispatch_failed(dispatch_res):
            elements = dispatch_res
            result_text = "요소 목록을 읽었습니다"

        parts = [
            f"관찰: 직전 동작 '{action}'의 결과는 '{result_text}'입니다.",
            f"현재 활성 앱: {front or '알 수 없음'}"
            + (f" — 창 제목: \"{win_title}\"" if win_title else "") + ".",
        ]
        if step_history:
            parts.append(self._step_summary(step_history))
        parts.append(
            "이미 수행한 동작을 반복하지 마세요. "
            "요청의 다음 미완료 부분을 수행하거나, 전부 끝났으면 done=true로 응답하세요."
        )
        text = "\n".join(parts)

        if action in ("read_screen", "click_element", "set_value"):
            # Window-use observations are text: after a click/set we re-read
            # the elements so the model verifies the result without a
            # screenshot.
            if action != "read_screen" and not _dispatch_failed(dispatch_res):
                time.sleep(_ELEMENT_SETTLE_SEC)
                elements = snapshot_screen()
            if elements is not None:
                text += "\n" + _ELEMENTS_MARKER + "\n" + elements
            return {"role": "user", "content": text}
        if (
            getattr(self._llm, "supports_vision", False) is True
            and action in _SCREEN_OBSERVATION_ACTIONS
        ):
            try:
                return self._llm.build_observation(text, take_screenshot_with_grid())
            except Exception:
                pass
        return {"role": "user", "content": text}

    def try_fast_path(self, command: str) -> str | None:
        parsed = parse_fast_path(command)
        if parsed is None:
            trace("agent.fast_path.miss", command=command)
            return None

        start = time.monotonic()
        action, params, response_text = parsed
        trace("agent.fast_path.selected", action=action, params=params)
        dangerous = self._guard.is_dangerous(action, params)
        if not self._guard.check(action, params):
            trace("agent.fast_path.blocked", action=action, reason="safety_guard")
            speak("작업을 취소했습니다.", self._tts.voice, self._tts.rate, tts_config=self._tts)
            final_response = "취소됨"
            elapsed_ms = int((time.monotonic() - start) * 1000)
            is_repeated = self._detector.record(command)
            self._context.add_turn(command, final_response)
            self._collector.record(command, 0.95, False, 0, dangerous, elapsed_ms, is_repeated)
            return final_response

        dispatch_res = tools.dispatch(action, params)
        failed = _dispatch_failed(dispatch_res)
        trace(
            "agent.fast_path.completed",
            action=action,
            dispatch_result=dispatch_res,
            failed=failed,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        final_response = (
            f"오류: 빠른 실행에 실패했어요. {dispatch_res}"
            if failed else response_text
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        is_repeated = self._detector.record(command)
        success = not failed

        self._context.add_turn(command, final_response)
        self._collector.record(command, 0.95, success, 0, dangerous, elapsed_ms, is_repeated)
        self._set_state("success" if success else "error")
        speak(final_response, self._tts.voice, self._tts.rate, tts_config=self._tts)
        if is_repeated:
            speak("이 명령을 루틴으로 저장할까요?", self._tts.voice, self._tts.rate, tts_config=self._tts)
        return final_response

    def run(self, command: str) -> str:
        try:
            return self._run(command)
        finally:
            # read_screen turns assistive-tech mode ON for the target app;
            # Chromium/Electron apps burn renderer CPU/memory for as long as
            # it stays on, so it must go back OFF however the command ends
            # (done, exhausted, safety-blocked, or an exception mid-loop).
            try:
                release_ax_flags()
            except Exception:
                pass

    def _run(self, command: str) -> str:
        start = time.monotonic()
        retry = 0
        trace(
            "agent.run.started",
            command=command,
            max_iterations=self._max_iterations,
            supports_vision=bool(getattr(self._llm, "supports_vision", False)),
        )

        # Each command decides its own target app (launch_app or first
        # read_screen) — never inherit the previous command's pin.
        try:
            clear_target_app()
        except Exception:
            pass

        # A cached action is the LLM's interpretation of a command UNDER the
        # memory state injected at the time — if the stable memory tiers
        # (profile/patterns) have changed since, that interpretation may no
        # longer match what the model would decide today, so drop the cache
        # instead of replaying it blindly forever.
        if self._retriever is not None:
            try:
                fp = self._retriever.fingerprint()
            except Exception:
                fp = self._memory_fingerprint  # unreadable → keep cache as-is
            if fp != self._memory_fingerprint:
                if self._memory_fingerprint is not None:
                    import sys
                    print("[Agent] Memory changed — hot cache invalidated.", file=sys.stderr)
                    trace("agent.cache.invalidated", reason="memory_changed")
                    self._cache.clear()
                self._memory_fingerprint = fp

        cached = self._cache.get(command)
        if cached:
            import sys
            print(f"[Agent] Cache HIT for command '{command}': {cached}", file=sys.stderr)
            trace("agent.cache.hit", command=command, cached_action=cached)
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
                    trace("agent.cache.blocked", action="launch_app", reason="invalid_app_name")
                    return f"error: invalid app name: {app}"
                print(f"[Agent] Executing cached launch_app for '{app}'...", file=sys.stderr)
                result = run_applescript(f'tell application "{app}" to activate')
            else:
                print(f"[Agent] Executing cached action '{action_str}' with {params_dict}...", file=sys.stderr)
                result = tools.dispatch(action_str, params_dict)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            failed = _dispatch_failed(result)
            self._log_action(command, action_str, params_dict, result)
            self._log_outcome(command, not failed, elapsed_ms)
            self._set_state("error" if failed else "success")
            if failed:
                speak("저장된 명령 실행에 실패했어요.", self._tts.voice, self._tts.rate, tts_config=self._tts)
            else:
                speak("완료했습니다.", self._tts.voice, self._tts.rate, tts_config=self._tts)
            self._collector.record(command, 0.99, not failed, 0, False, elapsed_ms, False)
            print(f"[Agent] Cache execution finished. Result: {result}", file=sys.stderr)
            trace(
                "agent.cache.completed",
                action=action_str,
                params=params_dict,
                dispatch_result=result,
                failed=failed,
                duration_ms=elapsed_ms,
            )
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
        # (action, params_json, dispatch_result) of every completed step — fed
        # into _observe so the LLM always sees the full history of what it has
        # done, preventing it from repeating actions blindly.
        step_history: list[tuple[str, dict, str]] = []
        # Track the previous step's (action, params) to detect identical
        # consecutive actions and nudge the model forward.
        prev_action_key: tuple[str, str] | None = None
        # Index in `messages` of the observation holding the LATEST element
        # listing, so it can be cut down once a newer listing supersedes it.
        last_elements_idx: int | None = None
        # Maintain one running message list so each step remembers the original
        # command and the assistant's prior actions/observations.
        memory_block = None
        if self._retriever:
            try:
                memory_block = self._retriever.build_memory_block(command)
            except Exception as e:
                import sys
                print(f"[Memory] retrieval failed: {e}", file=sys.stderr)
                trace("memory.retrieval.failed", error_type=type(e).__name__, error=str(e))
        messages = self._context.to_messages(command, memory_block=memory_block)
        trace("llm.session.started", message_count=len(messages), memory_attached=bool(memory_block))
        for i in range(self._max_iterations):
            llm_started = time.monotonic()
            trace("llm.request.started", iteration=i + 1, message_count=len(messages))
            try:
                raw = self._llm.complete(messages)
            except Exception as e:
                import sys
                print(f"[Agent] LLM call FAILED: {type(e).__name__}: {e}", file=sys.stderr)
                trace(
                    "llm.request.failed",
                    iteration=i + 1,
                    duration_ms=int((time.monotonic() - llm_started) * 1000),
                    error_type=type(e).__name__,
                    error=str(e),
                )
                if "Connection" in type(e).__name__ or "Connection" in str(e):
                    final_response = "오류: LLM 서버에 연결할 수 없어요. 설정에서 LLM 상태를 확인해 주세요."
                else:
                    final_response = "오류: 명령을 처리하지 못했어요. LLM 설정을 확인해 주세요."
                break

            trace(
                "llm.request.completed",
                iteration=i + 1,
                duration_ms=int((time.monotonic() - llm_started) * 1000),
                raw_response=raw,
            )

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
            # Drop any explanation the LLM added BEFORE the JSON.
            brace_idx = raw_clean.find('{')
            if brace_idx != -1:
                raw_clean = raw_clean[brace_idx:]

            print(f"[Agent] Cleaned response for JSON parsing:\n{raw_clean}\n-----------------", file=sys.stderr)
            try:
                # Parse only the FIRST complete JSON object. Weaker/local
                # models routinely pre-plan several future steps as extra
                # JSON objects (or trailing "Observation: ..." prose) in one
                # reply even though the system prompt asks for exactly one —
                # a plain json.loads() on the whole text then fails with
                # "Extra data" even though a valid single step is right
                # there at the start. raw_decode() reads just that first
                # object and reports where it ended, ignoring the rest; the
                # loop naturally asks for the next step on the next
                # iteration anyway.
                parsed, _ = json.JSONDecoder().raw_decode(raw_clean)
            except json.JSONDecodeError as e:
                print(f"[Agent] JSON parsing FAILED. Error: {e}", file=sys.stderr)
                print(f"[Agent] Raw output was: {raw}", file=sys.stderr)
                trace(
                    "llm.response.invalid_json",
                    iteration=i + 1,
                    error=str(e),
                    json_retries=json_retries,
                    raw_response=raw,
                )
                if json_retries < MAX_JSON_RETRIES and i < self._max_iterations - 1:
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
            trace(
                "agent.decision",
                iteration=i + 1,
                action=action,
                params=params,
                done=done,
                response=response_text,
            )

            dangerous = self._guard.is_dangerous(action, params)
            if dangerous:
                print(f"[Agent] Action flagged as DANGEROUS: {action}", file=sys.stderr)
                trace("agent.decision.requires_confirmation", action=action, params=params)
                self._set_state("danger_confirm")
                had_dangerous = True
                retry += 1

            if not self._guard.check(action, params):
                print(f"[Agent] Action BLOCKED by Safety Guard: {action} with {params}", file=sys.stderr)
                trace("agent.decision.denied", action=action, params=params)
                speak("작업을 취소했습니다.", self._tts.voice, self._tts.rate, tts_config=self._tts)
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
                trace("tool.dispatch.blocked", action=action, reason="vision_not_supported")
            else:
                print(f"[Agent] Dispatching action '{action}' with {params}...", file=sys.stderr)
                trace("tool.dispatch.started", iteration=i + 1, action=action, params=params)
                dispatch_res = tools.dispatch(action, params)
            last_dispatch = dispatch_res
            print(f"[Agent] Dispatch result: '{dispatch_res}'", file=sys.stderr)
            trace(
                "tool.dispatch.completed",
                iteration=i + 1,
                action=action,
                dispatch_result=dispatch_res,
                failed=_dispatch_failed(dispatch_res),
            )
            self._log_action(command, action, params, dispatch_res)
            step_history.append((action, params, dispatch_res))
            # Same replay-safety reasoning as the hot cache: a saved routine
            # replays steps blindly via tools.dispatch with no LLM in the
            # loop, so an id from read_screen/click_element/set_value would
            # be meaningless (or worse, refer to a different element) on a
            # later run against a different screen state.
            if action not in _UNCACHEABLE_ACTIONS and not _dispatch_failed(dispatch_res):
                executed_steps.append({"action": action, "params": params})

            if done:
                if _dispatch_failed(dispatch_res):
                    # Harness gate (verify before done): an action that just
                    # failed cannot claim completion. Reject done=true and fall
                    # through to the observation so the model can correct
                    # itself or report the failure honestly.
                    print(f"[Agent] done=true REJECTED: last action failed ('{dispatch_res}')", file=sys.stderr)
                    trace("agent.done_rejected", action=action, dispatch_result=dispatch_res)
                else:
                    # Only single-step, real actions are safe to cache: a
                    # multi-step command can't be replayed from one action and
                    # a speak_only reply would lose its answer on replay.
                    if i == 0 and action not in _UNCACHEABLE_ACTIONS:
                        self._cache.record(command, f"{action}:{json.dumps(params)}")
                    final_response = response_text
                    break

            # Feed an observation of the current state back so the LLM can
            # verify success and continue. Vision-capable providers get a
            # screenshot; others get a text-only observation.
            if action != "speak_only" and i < self._max_iterations - 1:
                # Detect identical consecutive actions: the model is stuck
                # repeating itself (e.g. opening the same URL twice).
                cur_key = (action, json.dumps(params, sort_keys=True))
                if cur_key == prev_action_key:
                    print(f"[Agent] Duplicate action detected: {action} {params}", file=sys.stderr)
                    trace("agent.duplicate_action", action=action, params=params)
                    messages.append({"role": "user", "content": (
                        f"주의: 방금 '{action}'을(를) 동일한 파라미터로 다시 실행했습니다. "
                        "이 동작은 이미 이전 단계에서 완료되었으니 반복하지 마세요. "
                        "요청의 아직 수행하지 않은 다음 부분으로 넘어가세요."
                    )})
                else:
                    obs = self._observe(action, dispatch_res,
                                        step_history=step_history)
                    if (isinstance(obs.get("content"), str)
                            and _ELEMENTS_MARKER in obs["content"]):
                        _mark_stale_elements(messages, last_elements_idx)
                        last_elements_idx = len(messages)
                    messages.append(obs)
                prev_action_key = cur_key

        elapsed_ms = int((time.monotonic() - start) * 1000)
        success = bool(
            final_response
            and final_response != "취소됨"
            and not final_response.startswith("오류")
            and not _dispatch_failed(last_dispatch)
        )
        # The loop ran out of steps before the model set done=true (a long or
        # under-specified command). Without this the user would hear silence,
        # which reads as "no response". Give spoken feedback instead.
        if not final_response:
            final_response = "오류: 명령을 끝까지 완료하지 못했어요. 좀 더 구체적으로 다시 말씀해 주세요."
            print("[Agent] Loop ended without a final response; using fallback.", file=sys.stderr)
            trace("agent.run.exhausted", max_iterations=self._max_iterations)

        is_repeated = self._detector.record(command)
        self._context.add_turn(command, final_response)
        self._log_outcome(command, success, elapsed_ms, final_response)
        self._collector.record(command, 0.95, success, retry,
                               self._guard.is_dangerous(action, params),
                               elapsed_ms, is_repeated)
        trace(
            "agent.run.completed",
            success=success,
            retry_count=retry,
            final_action=action,
            final_response=final_response,
            duration_ms=elapsed_ms,
        )

        # speak() blocks until the audio finishes playing (can be several
        # seconds for a long response, longer still when NVIDIA TTS fails and
        # falls back to local voice). Tell the HUD the outcome BEFORE that
        # call so it shows success/error immediately instead of sitting on
        # "명령 수행 중..." for the entire time the response is being read
        # aloud — otherwise a long spoken reply looks exactly like a hang.
        self._set_state("success" if success else "error")

        if final_response:
            speak(final_response, self._tts.voice, self._tts.rate, tts_config=self._tts)
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
            speak("이 명령을 루틴으로 저장할까요?", self._tts.voice, self._tts.rate, tts_config=self._tts)
            answer = parse_yes_no(self._listen_confirm())
            if answer is True:
                self._routines.save(command, steps)
                speak("루틴으로 저장했어요.", self._tts.voice, self._tts.rate, tts_config=self._tts)
            elif answer is False:
                speak("알겠어요.", self._tts.voice, self._tts.rate, tts_config=self._tts)
        except Exception as e:
            print(f"[Agent] routine-save offer failed: {e}", file=sys.stderr)
