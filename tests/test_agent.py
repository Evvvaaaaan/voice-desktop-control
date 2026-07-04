import pytest
from unittest.mock import MagicMock, patch
from agent.cache import HotCommandCache
from agent.context import ConversationContext
from agent.core import Agent
from agent.tools import dispatch


def test_hot_cache_miss_returns_none():
    cache = HotCommandCache()
    assert cache.get("사파리 열어줘") is None


def test_hot_cache_hit_after_population():
    cache = HotCommandCache()
    cache.record("사파리 열어줘", "launch_safari")
    cache.record("사파리 열어줘", "launch_safari")
    cache.record("사파리 열어줘", "launch_safari")
    assert cache.get("사파리 열어줘") == "launch_safari"


def test_context_window_keeps_last_5():
    ctx = ConversationContext(max_turns=5)
    for i in range(7):
        ctx.add_turn(f"user msg {i}", f"assistant msg {i}")
    messages = ctx.to_messages()
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert len(user_msgs) == 5
    assert user_msgs[0]["content"] == "user msg 2"


def test_agent_run_uses_cache(mocker):
    mock_llm = MagicMock()
    mock_guard = MagicMock()
    mock_guard.check.return_value = True
    mock_collector = MagicMock()
    mock_detector = MagicMock()
    mock_detector.record.return_value = False
    mock_tts_cfg = MagicMock(voice="Yuna", rate=200)

    agent = Agent(mock_llm, mock_guard, mock_collector, mock_detector, mock_tts_cfg)
    agent._cache._cache["사파리 열어줘"] = ("launch_app:Safari", 5)

    with patch("agent.core.speak") as mock_speak, \
         patch("agent.core.run_applescript", return_value=""):
        result = agent.run("사파리 열어줘")

    mock_llm.complete.assert_not_called()


def test_dispatch_launch_app_rejects_injection():
    result = dispatch("launch_app", {"app": 'Safari"; do shell script "rm -rf ~'})
    assert result.startswith("error: invalid app name")


def test_dispatch_launch_app_valid(mocker):
    mocker.patch("agent.tools.run_applescript", return_value="activated")
    result = dispatch("launch_app", {"app": "Safari"})
    assert result == "activated"


def test_dispatch_run_routine_success(mocker):
    with patch("routines.manager.RoutineManager") as MockMgr:
        MockMgr.return_value.execute.return_value = True
        result = dispatch("run_routine", {"name": "morning"})
    assert result == "routine_done"


def test_dispatch_run_routine_not_found(mocker):
    with patch("routines.manager.RoutineManager") as MockMgr:
        MockMgr.return_value.execute.return_value = False
        result = dispatch("run_routine", {"name": "nonexistent"})
    assert result == "routine_failed"


def test_agent_run_calls_llm_on_cache_miss(mocker):
    mock_llm = MagicMock()
    mock_llm.complete.return_value = '{"action": "launch_app", "params": {"app": "Safari"}, "done": true, "response": "사파리를 열었습니다"}'
    mock_guard = MagicMock()
    mock_guard.check.return_value = True
    mock_guard.is_dangerous.return_value = False
    mock_collector = MagicMock()
    mock_detector = MagicMock()
    mock_detector.record.return_value = False
    mock_tts_cfg = MagicMock(voice="Yuna", rate=200)

    agent = Agent(mock_llm, mock_guard, mock_collector, mock_detector, mock_tts_cfg)
    with patch("agent.core.speak"), patch("agent.core.run_applescript", return_value=""):
        result = agent.run("사파리 열어줘")

    mock_llm.complete.assert_called()
    assert "사파리" in result or result != ""


def test_dispatch_open_url_valid(mocker):
    mock_run = mocker.patch("agent.tools.run_applescript", return_value="")
    result = dispatch("open_url", {"url": "https://www.google.com/search?q=gmail"})
    mock_run.assert_called_once()
    assert "open location" in mock_run.call_args[0][0]
    assert "https://www.google.com/search?q=gmail" in mock_run.call_args[0][0]


def test_dispatch_open_url_rejects_non_http():
    result = dispatch("open_url", {"url": "file:///etc/passwd"})
    assert result.startswith("error: invalid url")


def test_dispatch_open_url_rejects_injection():
    result = dispatch("open_url", {"url": 'https://x"; do shell script "rm -rf ~'})
    assert result.startswith("error: invalid url")


def _make_agent(mock_llm):
    mock_guard = MagicMock()
    mock_guard.check.return_value = True
    mock_guard.is_dangerous.return_value = False
    mock_detector = MagicMock()
    mock_detector.record.return_value = False
    mock_tts_cfg = MagicMock(voice="Yuna", rate=200)
    return Agent(mock_llm, mock_guard, MagicMock(), mock_detector, mock_tts_cfg)


def test_agent_runs_multiple_steps_until_done(mocker):
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.side_effect = [
        '{"action": "launch_app", "params": {"app": "Google Chrome"}, "done": false, "response": "여는 중"}',
        '{"action": "open_url", "params": {"url": "https://www.google.com/search?q=gmail"}, "done": true, "response": "검색했어요"}',
    ]
    agent = _make_agent(mock_llm)

    dispatch_calls = []
    mocker.patch("agent.core.tools.dispatch", side_effect=lambda a, p: dispatch_calls.append(a) or "ok")
    mock_shot = mocker.patch("agent.core.take_screenshot_with_grid", return_value=b"png")
    mocker.patch("agent.core.run_applescript", return_value="Google Chrome")
    mocker.patch("agent.core.speak")

    result = agent.run("크롬 열고 gmail 검색해줘")

    assert dispatch_calls == ["launch_app", "open_url"]
    assert result == "검색했어요"
    # non-vision provider must not incur a screenshot
    mock_shot.assert_not_called()
    # step 2 must still carry the original command + the step-1 assistant action
    second_call_messages = mock_llm.complete.call_args_list[1].args[0]
    roles = [m["role"] for m in second_call_messages]
    assert "assistant" in roles
    assert any(
        isinstance(m.get("content"), str) and "크롬 열고 gmail" in m["content"]
        for m in second_call_messages
    )


def test_agent_multistep_command_not_cached(mocker):
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.side_effect = [
        '{"action": "launch_app", "params": {"app": "Google Chrome"}, "done": false, "response": "여는 중"}',
        '{"action": "open_url", "params": {"url": "https://mail.google.com"}, "done": true, "response": "완료"}',
    ]
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="ok")
    mocker.patch("agent.core.run_applescript", return_value="")
    mocker.patch("agent.core.speak")

    cmd = "크롬 열고 gmail 열어줘"
    agent.run(cmd)

    # A multi-step command must never be cached as a single action.
    assert agent._cache.get(cmd) is None
    assert agent._cache._freq.get(cmd, 0) == 0


def test_agent_vision_provider_feeds_screenshot(mocker):
    mock_llm = MagicMock()
    mock_llm.supports_vision = True
    mock_llm.build_observation.return_value = {"role": "user", "content": "obs"}
    mock_llm.complete.side_effect = [
        '{"action": "launch_app", "params": {"app": "Safari"}, "done": false, "response": "여는 중"}',
        '{"action": "speak_only", "params": {}, "done": true, "response": "완료"}',
    ]
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="ok")
    mock_shot = mocker.patch("agent.core.take_screenshot_with_grid", return_value=b"png")
    mocker.patch("agent.core.run_applescript", return_value="Safari")
    mocker.patch("agent.core.speak")

    agent.run("사파리 열어줘")

    mock_shot.assert_called()
    mock_llm.build_observation.assert_called_once()


def test_agent_set_llm_replaces_runtime_adapter():
    old_llm = MagicMock()
    new_llm = MagicMock()
    mock_guard = MagicMock()
    mock_collector = MagicMock()
    mock_detector = MagicMock()
    mock_tts_cfg = MagicMock(voice="Yuna", rate=200)

    agent = Agent(old_llm, mock_guard, mock_collector, mock_detector, mock_tts_cfg)
    agent.set_llm(new_llm)

    assert agent._llm is new_llm


# ---------------------------------------------------------------------------
# Error handling & cache-poisoning regressions
# ---------------------------------------------------------------------------

def test_agent_run_survives_llm_connection_error(mocker):
    """LLM being unreachable (e.g. Ollama not running) must not raise."""
    mock_llm = MagicMock()
    mock_llm.complete.side_effect = ConnectionError("connection refused")
    agent = _make_agent(mock_llm)
    mock_speak = mocker.patch("agent.core.speak")

    result = agent.run("사파리 열어줘")

    assert result.startswith("오류")
    assert "연결" in result
    mock_speak.assert_called()          # the error is spoken to the user
    # metrics record success=False
    success_arg = agent._collector.record.call_args.args[2]
    assert success_arg is False


def test_agent_run_survives_generic_llm_error(mocker):
    mock_llm = MagicMock()
    mock_llm.complete.side_effect = RuntimeError("boom")
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.speak")
    result = agent.run("사파리 열어줘")
    assert result.startswith("오류")


def test_speak_only_answers_are_never_cached(mocker):
    """Caching speak_only would replay '완료했습니다' instead of the answer."""
    mock_llm = MagicMock()
    mock_llm.complete.return_value = (
        '{"action": "speak_only", "params": {}, "done": true, "response": "맑아요"}'
    )
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="")
    mocker.patch("agent.core.speak")

    for _ in range(5):
        agent.run("오늘 날씨 알려줘")

    assert agent._cache.get("오늘 날씨 알려줘") is None


def test_failed_actions_are_never_cached(mocker):
    mock_llm = MagicMock()
    mock_llm.complete.return_value = (
        '{"action": "launch_app", "params": {"app": "NoSuchApp"}, "done": true, "response": "열었어요"}'
    )
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="error: app not found")
    mocker.patch("agent.core.speak")

    for _ in range(5):
        agent.run("없는앱 열어줘")

    assert agent._cache.get("없는앱 열어줘") is None


def test_failed_dispatch_records_failure(mocker):
    mock_llm = MagicMock()
    mock_llm.complete.return_value = (
        '{"action": "launch_app", "params": {"app": "NoSuchApp"}, "done": true, "response": "열었어요"}'
    )
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="error: app not found")
    mocker.patch("agent.core.speak")
    agent.run("없는앱 열어줘")
    success_arg = agent._collector.record.call_args.args[2]
    assert success_arg is False


def test_cached_error_result_not_spoken_as_success(mocker):
    mock_llm = MagicMock()
    agent = _make_agent(mock_llm)
    agent._cache._cache["없는앱 열어줘"] = ('launch_app:{"app": "NoSuchApp"}', 5)
    mock_speak = mocker.patch("agent.core.speak")
    mocker.patch("agent.core.run_applescript", return_value="error: not found")

    agent.run("없는앱 열어줘")

    spoken = mock_speak.call_args.args[0]
    assert "실패" in spoken
    success_arg = agent._collector.record.call_args.args[2]
    assert success_arg is False


def test_danger_confirm_state_reported_via_on_state(mocker):
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.return_value = (
        '{"action": "run_applescript", "params": {"script": "delete file x"}, "done": true, "response": "삭제했어요"}'
    )
    states = []
    mock_guard = MagicMock()
    mock_guard.is_dangerous.return_value = True
    mock_guard.check.return_value = True
    mock_detector = MagicMock()
    mock_detector.record.return_value = False
    agent = Agent(mock_llm, mock_guard, MagicMock(), mock_detector,
                  MagicMock(voice="Yuna", rate=200), on_state=states.append)
    mocker.patch("agent.core.tools.dispatch", return_value="ok")
    mocker.patch("agent.core.speak")

    agent.run("파일 삭제해줘")

    assert "danger_confirm" in states
    assert "executing" in states


# ---------------------------------------------------------------------------
# dispatch param validation (missing params must not raise KeyError)
# ---------------------------------------------------------------------------

def test_dispatch_click_missing_params_returns_error():
    assert dispatch("click", {}).startswith("error")


def test_dispatch_type_text_missing_params_returns_error():
    assert dispatch("type_text", {}).startswith("error")


def test_dispatch_press_key_missing_params_returns_error():
    assert dispatch("press_key", {}).startswith("error")


def test_dispatch_run_applescript_missing_params_returns_error():
    assert dispatch("run_applescript", {}).startswith("error")


def test_dispatch_launch_app_non_string_param():
    assert dispatch("launch_app", {"app": None}).startswith("error")


def test_system_prompt_tolerates_stt_mistranscriptions():
    """The prompt must tell the LLM the command text comes from speech
    recognition so phonetically-off commands still resolve."""
    from agent.context import SYSTEM_PROMPT
    assert "SPEECH RECOGNITION" in SYSTEM_PROMPT
    assert "크롬" in SYSTEM_PROMPT          # concrete Korean example included


# ---------------------------------------------------------------------------
# Computer-use: normalized 0..1000 coords → logical screen points
# ---------------------------------------------------------------------------

def test_click_maps_normalized_coords_to_screen(mocker):
    from agent import tools
    mocker.patch("agent.tools.active_screen_rect", return_value=(0.0, 0.0, 1000.0, 800.0))
    mock_click = mocker.patch("agent.tools.click")
    res = tools.dispatch("click", {"x": 500, "y": 250})
    mock_click.assert_called_once_with(500, 200)   # 50% of 1000, 25% of 800
    assert res.startswith("clicked at")


def test_click_clamps_inside_screen(mocker):
    from agent import tools
    mocker.patch("agent.tools.active_screen_rect", return_value=(0.0, 0.0, 1440.0, 900.0))
    mock_click = mocker.patch("agent.tools.click")
    tools.dispatch("click", {"x": 1000, "y": 1000})   # bottom-right corner
    x, y = mock_click.call_args.args
    assert x == 1438 and y == 898                     # clamped off the edge (failsafe guard)


def test_move_mouse_and_double_click_dispatch(mocker):
    from agent import tools
    mocker.patch("agent.tools.active_screen_rect", return_value=(0.0, 0.0, 1000.0, 1000.0))
    mock_move = mocker.patch("agent.tools.move_mouse")
    mock_dbl = mocker.patch("agent.tools.double_click")
    assert tools.dispatch("move_mouse", {"x": 100, "y": 100}).startswith("moved to")
    assert tools.dispatch("double_click", {"x": 200, "y": 300}).startswith("double_clicked")
    mock_move.assert_called_once_with(100, 100)
    mock_dbl.assert_called_once_with(200, 300)


def test_click_missing_coords_errors(mocker):
    from agent import tools
    mocker.patch("agent.tools.active_screen_rect", return_value=(0.0, 0.0, 1000.0, 1000.0))
    assert tools.dispatch("click", {}).startswith("error")
    assert tools.dispatch("move_mouse", {"x": 5}).startswith("error")


def test_loop_without_done_speaks_fallback(mocker):
    """A command the model never marks done must not end in silence."""
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    # Always returns done=false → loop exhausts MAX_ITERATIONS
    mock_llm.complete.return_value = (
        '{"action": "screenshot", "params": {}, "done": false, "response": ""}'
    )
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="screenshot_taken:10 bytes")
    mocker.patch("agent.core.take_screenshot_with_grid", return_value=b"png")
    mocker.patch("agent.core.run_applescript", return_value="")
    mock_speak = mocker.patch("agent.core.speak")

    result = agent.run("메일 들어가서 나한테 메일 써줘")

    assert result.startswith("오류")           # recognizable as failure by main.py
    mock_speak.assert_called()                  # user hears feedback, not silence
    success_arg = agent._collector.record.call_args.args[2]
    assert success_arg is False


def test_click_maps_onto_external_display_with_negative_origin(mocker):
    """Multi-display: coords must land on the ACTIVE display, which can sit at
    negative global x (e.g. an external monitor left of the main screen)."""
    from agent import tools
    mocker.patch("agent.tools.active_screen_rect",
                 return_value=(-1920.0, 0.0, 1920.0, 1080.0))
    mock_click = mocker.patch("agent.tools.click")
    tools.dispatch("click", {"x": 500, "y": 500})
    x, y = mock_click.call_args.args
    assert x == -960 and y == 540          # center of the external display


# ---------------------------------------------------------------------------
# Long text routes through the notch input
# ---------------------------------------------------------------------------

def test_long_type_text_routes_through_notch_input(mocker):
    from agent import tools
    mock_type = mocker.patch("agent.tools.type_text")
    tools.set_text_input_provider(lambda prompt, prefill: prefill + "!")
    try:
        res = tools.dispatch("type_text", {"text": "안녕하세요 반갑습니다"})   # ≥10 chars
        mock_type.assert_called_once_with("안녕하세요 반갑습니다!")           # user-edited
        assert res == "typed"
    finally:
        tools.set_text_input_provider(None)


def test_long_type_text_cancelled_by_user(mocker):
    from agent import tools
    mock_type = mocker.patch("agent.tools.type_text")
    tools.set_text_input_provider(lambda prompt, prefill: None)
    try:
        res = tools.dispatch("type_text", {"text": "안녕하세요 반갑습니다"})
        assert res.startswith("error")
        mock_type.assert_not_called()
    finally:
        tools.set_text_input_provider(None)


def test_short_type_text_skips_notch_input(mocker):
    from agent import tools
    mock_type = mocker.patch("agent.tools.type_text")
    called = []
    tools.set_text_input_provider(lambda p, f: called.append(1) or f)
    try:
        tools.dispatch("type_text", {"text": "ok"})       # short → direct
        assert not called
        mock_type.assert_called_once_with("ok")
    finally:
        tools.set_text_input_provider(None)


# ---------------------------------------------------------------------------
# Harness gate: verify-before-done — a failed action cannot claim completion
# ---------------------------------------------------------------------------

def test_done_rejected_when_final_action_fails_then_recovers(mocker):
    """done=true on a failed dispatch must NOT end the loop: the model gets the
    error observation back and can correct itself on the next step."""
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.side_effect = [
        '{"action": "launch_app", "params": {"app": "NoSuchApp"}, "done": true, "response": "열었어요"}',
        '{"action": "launch_app", "params": {"app": "Safari"}, "done": true, "response": "사파리를 열었어요"}',
    ]
    agent = _make_agent(mock_llm)
    mocker.patch(
        "agent.core.tools.dispatch",
        side_effect=lambda a, p: "error: app not found" if p.get("app") == "NoSuchApp" else "ok",
    )
    mocker.patch("agent.core.run_applescript", return_value="Finder")
    mocker.patch("agent.core.speak")

    result = agent.run("없는앱 아니면 사파리 열어줘")

    assert result == "사파리를 열었어요"
    # The second LLM call must have seen the error observation.
    second_call_messages = mock_llm.complete.call_args_list[1].args[0]
    assert any(
        isinstance(m.get("content"), str) and "error: app not found" in m["content"]
        for m in second_call_messages
    )


def test_false_success_claim_never_spoken_when_action_keeps_failing(mocker):
    """If every attempt fails, the model's '열었어요' claim must never be spoken
    or returned — the honest fallback error is used instead."""
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.return_value = (
        '{"action": "launch_app", "params": {"app": "NoSuchApp"}, "done": true, "response": "열었어요"}'
    )
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="error: app not found")
    mocker.patch("agent.core.run_applescript", return_value="Finder")
    mock_speak = mocker.patch("agent.core.speak")

    result = agent.run("없는앱 열어줘")

    assert "열었어요" not in result
    assert result.startswith("오류")
    spoken = [c.args[0] for c in mock_speak.call_args_list]
    assert all("열었어요" not in s for s in spoken)
    success_arg = agent._collector.record.call_args.args[2]
    assert success_arg is False


def test_success_state_reported_before_speak_blocks(mocker):
    """Regression: agent.run() blocked inside speak() (TTS playback, several
    seconds for a long response or an NVIDIA→local fallback) with the HUD
    stuck showing '명령 수행 중...' the whole time, because on_state was
    never called until AFTER speak() returned. The final state must be
    reported to the HUD before speak() is invoked, not after."""
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.return_value = (
        '{"action": "speak_only", "params": {}, "done": true, "response": "완료했어요"}'
    )
    states = []
    call_order = []

    def fake_speak(*a, **kw):
        call_order.append("speak")

    mocker.patch("agent.core.speak", side_effect=fake_speak)

    def track_state(s):
        states.append(s)
        call_order.append(f"state:{s}")

    mock_guard = MagicMock()
    mock_guard.is_dangerous.return_value = False
    mock_guard.check.return_value = True
    mock_detector = MagicMock()
    mock_detector.record.return_value = False
    agent = Agent(mock_llm, mock_guard, MagicMock(), mock_detector,
                  MagicMock(voice="Yuna", rate=200), on_state=track_state)

    agent.run("완료 상태 확인")

    assert "success" in states
    # The state transition must happen strictly before the speak() call that
    # blocks on audio playback — not after.
    assert call_order.index("state:success") < call_order.index("speak")


def test_error_state_reported_before_speak_on_incomplete_command(mocker):
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.return_value = (
        '{"action": "screenshot", "params": {}, "done": false, "response": ""}'
    )
    call_order = []
    mocker.patch("agent.core.tools.dispatch", return_value="screenshot_taken:1 bytes")
    mocker.patch("agent.core.take_screenshot_with_grid", return_value=b"png")
    mocker.patch("agent.core.run_applescript", return_value="")
    mocker.patch("agent.core.speak", side_effect=lambda *a, **kw: call_order.append("speak"))

    def track_state(s):
        call_order.append(f"state:{s}")

    mock_guard = MagicMock()
    mock_guard.is_dangerous.return_value = False
    mock_guard.check.return_value = True
    mock_detector = MagicMock()
    mock_detector.record.return_value = False
    agent = Agent(mock_llm, mock_guard, MagicMock(), mock_detector,
                  MagicMock(voice="Yuna", rate=200), on_state=track_state)

    agent.run("영원히 안 끝나는 명령")

    assert "state:error" in call_order
    assert call_order.index("state:error") < call_order.index("speak")


def test_think_block_stripped_before_json_parsing(mocker):
    """Reasoning models (e.g. deepseek-v4-pro via NVIDIA NIM) prepend a
    <think>...</think> block; the JSON after it must still parse."""
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.return_value = (
        '<think>I should launch Safari for this.</think>'
        '{"action": "launch_app", "params": {"app": "Safari"}, "done": true, "response": "사파리를 열었습니다"}'
    )
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="ok")
    mocker.patch("agent.core.speak")

    result = agent.run("사파리 열어줘")

    assert result == "사파리를 열었습니다"


def test_orphan_closing_think_tag_stripped(mocker):
    """Some providers start the turn already inside 'thinking' mode via their
    chat template, so only a stray closing </think> comes back (no opener) —
    must still be stripped before JSON extraction."""
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.return_value = (
        'Step 1: launch Safari.</think>'
        '{"action": "launch_app", "params": {"app": "Safari"}, "done": true, "response": "사파리를 열었습니다"}'
    )
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="ok")
    mocker.patch("agent.core.speak")

    result = agent.run("사파리 열어줘")

    assert result == "사파리를 열었습니다"


def test_invalid_json_retried_then_recovers(mocker):
    """A malformed first reply (no JSON at all) must trigger a corrective
    re-prompt rather than being spoken verbatim; a valid reply on retry
    completes the command normally."""
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.side_effect = [
        '유튜브 화면을 확인하고 재생 버튼을 누를게요.',
        '{"action": "launch_app", "params": {"app": "Safari"}, "done": true, "response": "사파리를 열었습니다"}',
    ]
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="ok")
    mock_speak = mocker.patch("agent.core.speak")

    result = agent.run("사파리 열어줘")

    assert result == "사파리를 열었습니다"
    assert mock_llm.complete.call_count == 2
    # the corrective message must have been sent back to the model
    second_call_messages = mock_llm.complete.call_args_list[1].args[0]
    assert any(
        isinstance(m.get("content"), str) and "유효한 JSON이 아니었어요" in m["content"]
        for m in second_call_messages
    )
    mock_speak.assert_called_once_with("사파리를 열었습니다", "Yuna", 200, tts_config=agent._tts)


def test_persistently_invalid_json_falls_back_honestly(mocker):
    """If the model never produces JSON even after retries, the raw prose
    (which may contain reasoning/stray tags) must never be spoken — only the
    safe fallback message."""
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.return_value = 'Step 1: take a screenshot.</think>화면을 확인할게요.'
    agent = _make_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="ok")
    mock_speak = mocker.patch("agent.core.speak")

    result = agent.run("사파리 열어줘")

    assert result.startswith("오류")
    assert "Step 1" not in result
    assert "</think>" not in result
    spoken = [c.args[0] for c in mock_speak.call_args_list]
    assert all("Step 1" not in s and "</think>" not in s for s in spoken)
    # 1 initial attempt + MAX_JSON_RETRIES retries, capped by the shared budget
    from agent.core import MAX_JSON_RETRIES
    assert mock_llm.complete.call_count == 1 + MAX_JSON_RETRIES


def test_cached_result_state_reported_before_speak(mocker):
    mock_llm = MagicMock()
    call_order = []
    mocker.patch("agent.core.run_applescript", return_value="")
    mocker.patch("agent.core.speak", side_effect=lambda *a, **kw: call_order.append("speak"))

    def track_state(s):
        call_order.append(f"state:{s}")

    agent = Agent(mock_llm, MagicMock(), MagicMock(), MagicMock(),
                  MagicMock(voice="Yuna", rate=200), on_state=track_state)
    agent._cache._cache["사파리 열어줘"] = ('launch_app:{"app": "Safari"}', 5)

    agent.run("사파리 열어줘")

    assert "state:success" in call_order
    assert call_order.index("state:success") < call_order.index("speak")
