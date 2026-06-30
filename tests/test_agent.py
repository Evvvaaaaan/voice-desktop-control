import pytest
from unittest.mock import MagicMock, patch
from agent.cache import HotCommandCache
from agent.context import ConversationContext
from agent.core import Agent


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
