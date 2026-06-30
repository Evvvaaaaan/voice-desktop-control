import pytest
from unittest.mock import MagicMock, patch
from config.loader import Config, LLMConfig
from llm import get_llm_adapter
from llm.base import LLMBase


def make_config(provider: str, **kwargs) -> Config:
    cfg = Config()
    cfg.llm.provider = provider
    for k, v in kwargs.items():
        setattr(cfg.llm, k, v)
    return cfg


def test_get_adapter_returns_base():
    config = make_config("ollama")
    adapter = get_llm_adapter(config)
    assert isinstance(adapter, LLMBase)


def test_claude_adapter(mocker):
    from llm.claude_adapter import ClaudeAdapter
    mock_anthropic = mocker.patch("llm.claude_adapter.anthropic.Anthropic")
    mock_client = mock_anthropic.return_value
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(type="text", text="사파리 열었습니다")]
    mock_client.messages.create.return_value = mock_msg
    adapter = ClaudeAdapter(api_key="sk-ant-test", model="claude-sonnet-4-6")
    result = adapter.complete([{"role": "user", "content": "사파리 열어줘"}])
    assert result == "사파리 열었습니다"


def test_openai_adapter(mocker):
    from llm.openai_adapter import OpenAIAdapter
    mock_openai = mocker.patch("llm.openai_adapter.OpenAI")
    mock_client = mock_openai.return_value
    mock_choice = MagicMock()
    mock_choice.message.content = "done"
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    adapter = OpenAIAdapter(api_key="sk-test", model="gpt-4o")
    result = adapter.complete([{"role": "user", "content": "hi"}])
    assert result == "done"


def test_ollama_adapter(mocker):
    from llm.ollama_adapter import OllamaAdapter
    mock_post = mocker.patch("llm.ollama_adapter.requests.post")
    mock_post.return_value = MagicMock(
        json=lambda: {"message": {"content": "완료"}},
        raise_for_status=lambda: None,
    )
    adapter = OllamaAdapter(url="http://localhost:11434", model="llama3")
    result = adapter.complete([{"role": "user", "content": "안녕"}])
    assert result == "완료"
