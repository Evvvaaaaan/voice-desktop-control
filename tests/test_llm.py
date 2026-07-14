import pytest
from unittest.mock import MagicMock, patch
from config.loader import Config
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
    # system message must NOT appear inside the messages array
    call_kwargs = mock_client.messages.create.call_args[1]
    for msg in call_kwargs.get("messages", []):
        assert msg.get("role") != "system", "system role must not appear in messages array"


def test_claude_adapter_system_prompt_extracted(mocker):
    from llm.claude_adapter import ClaudeAdapter
    mock_anthropic = mocker.patch("llm.claude_adapter.anthropic.Anthropic")
    mock_client = mock_anthropic.return_value
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(type="text", text="ok")]
    mock_client.messages.create.return_value = mock_msg
    adapter = ClaudeAdapter(api_key="sk-ant-test", model="claude-sonnet-4-6")
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "안녕"},
    ]
    adapter.complete(messages)
    call_kwargs = mock_client.messages.create.call_args[1]
    # system prompt is passed as top-level param
    assert call_kwargs.get("system") == "You are a helpful assistant."
    # messages array contains only the user turn
    assert len(call_kwargs["messages"]) == 1
    assert call_kwargs["messages"][0]["role"] == "user"


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


def _mock_ollama_post(mocker, capabilities=(), chat_content="완료"):
    """OllamaAdapter now hits two different endpoints: /api/show (vision
    capability check, at construction) and /api/chat (complete()) — route
    the shared requests.post mock by URL like the real server would."""
    def _dispatch(url, json=None, timeout=None):
        if url.endswith("/api/show"):
            return MagicMock(
                json=lambda: {"capabilities": list(capabilities)},
                raise_for_status=lambda: None,
            )
        return MagicMock(
            status_code=200,
            json=lambda: {"message": {"content": chat_content}},
            raise_for_status=lambda: None,
        )
    return mocker.patch("llm.ollama_adapter.requests.post", side_effect=_dispatch)


def test_ollama_adapter(mocker):
    from llm.ollama_adapter import OllamaAdapter
    _mock_ollama_post(mocker, chat_content="완료")
    adapter = OllamaAdapter(url="http://localhost:11434", model="llama3")
    result = adapter.complete([{"role": "user", "content": "안녕"}])
    assert result == "완료"


def test_claude_supports_vision_and_builds_image_observation(mocker):
    from llm.claude_adapter import ClaudeAdapter
    mocker.patch("llm.claude_adapter.anthropic.Anthropic")
    adapter = ClaudeAdapter(api_key="sk-ant-test")
    assert adapter.supports_vision is True
    obs = adapter.build_observation("상태입니다", b"\x89PNG_bytes")
    assert obs["role"] == "user"
    types = [b["type"] for b in obs["content"]]
    assert "image" in types and "text" in types
    img = next(b for b in obs["content"] if b["type"] == "image")
    assert img["source"]["type"] == "base64"


def test_openai_supports_vision_and_builds_image_url_observation(mocker):
    from llm.openai_adapter import OpenAIAdapter
    mocker.patch("llm.openai_adapter.OpenAI")
    adapter = OpenAIAdapter(api_key="sk-test")
    assert adapter.supports_vision is True
    obs = adapter.build_observation("state", b"\x89PNG_bytes")
    img = next(b for b in obs["content"] if b["type"] == "image_url")
    assert img["image_url"]["url"].startswith("data:image/png;base64,")


def test_ollama_is_not_vision_capable(mocker):
    from llm.ollama_adapter import OllamaAdapter
    _mock_ollama_post(mocker, capabilities=["completion"])
    adapter = OllamaAdapter(url="http://localhost:11434", model="llama3")
    assert adapter.supports_vision is False


def test_ollama_vision_is_per_model(mocker):
    """Ollama hosts multimodal local models too. Capability must come from
    Ollama's own /api/show, not a model-name guess — name-based heuristics
    get this wrong: e.g. gemma4:e4b/gemma4:e2b (Gemma is natively multimodal
    at every size) report "vision" from /api/show even though this Ollama
    version's /api/tags listing omits it for those exact tags, so even a
    family-name match can't be trusted without checking the installed tag."""
    from llm.ollama_adapter import OllamaAdapter
    _mock_ollama_post(mocker, capabilities=["completion", "tools"])
    assert OllamaAdapter(model="llama3").supports_vision is False
    _mock_ollama_post(mocker, capabilities=["completion", "vision", "tools"])
    assert OllamaAdapter(model="gemma4:e4b").supports_vision is True


def test_ollama_vision_check_defaults_to_false_when_unreachable(mocker):
    """Ollama not running yet / model not pulled must not crash adapter
    construction — just fall back to the same non-vision default."""
    from llm.ollama_adapter import OllamaAdapter
    mocker.patch("llm.ollama_adapter.requests.post", side_effect=ConnectionError("down"))
    adapter = OllamaAdapter(model="gemma4:e4b")
    assert adapter.supports_vision is False


def test_ollama_builds_native_image_observation(mocker):
    """Ollama's /api/chat wants images as bare base64 in an "images" list,
    not an OpenAI-style data URI content block."""
    from llm.ollama_adapter import OllamaAdapter
    import base64
    _mock_ollama_post(mocker, capabilities=["completion", "vision"])
    adapter = OllamaAdapter(model="gemma4:e4b")
    obs = adapter.build_observation("상태입니다", b"\x89PNG_bytes")
    assert obs["role"] == "user"
    assert obs["content"] == "상태입니다"
    assert obs["images"] == [base64.b64encode(b"\x89PNG_bytes").decode()]


def test_nvidia_adapter_uses_nvidia_base_url(mocker):
    from llm.nvidia_adapter import NvidiaAdapter, NVIDIA_BASE_URL
    mock_openai_cls = mocker.patch("llm.nvidia_adapter.OpenAI")
    NvidiaAdapter(api_key="nvapi-test", model="minimaxai/minimax-m3")
    kwargs = mock_openai_cls.call_args.kwargs
    assert kwargs["api_key"] == "nvapi-test"
    assert kwargs["base_url"] == NVIDIA_BASE_URL
    assert kwargs["timeout"] > 0        # bounded so a stalled call can't hang


def test_nvidia_adapter_completes_like_openai(mocker):
    from llm.nvidia_adapter import NvidiaAdapter
    mock_openai_cls = mocker.patch("llm.nvidia_adapter.OpenAI")
    mock_client = mock_openai_cls.return_value
    mock_choice = MagicMock()
    mock_choice.message.content = "완료"
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    adapter = NvidiaAdapter(api_key="nvapi-test")
    result = adapter.complete([{"role": "user", "content": "안녕"}])
    assert result == "완료"


def test_nvidia_vision_is_per_model(mocker):
    # Vision must be enabled for multimodal models (deepseek-v4-pro, *-vision)
    # and off for text-only ones (minimax-m3) that hang on image payloads.
    mocker.patch("llm.nvidia_adapter.OpenAI")
    from llm.nvidia_adapter import NvidiaAdapter
    assert NvidiaAdapter(api_key="k", model="deepseek-ai/deepseek-v4-pro").supports_vision is True
    assert NvidiaAdapter(
        api_key="k", model="meta/llama-4-maverick-17b-128e-instruct"
    ).supports_vision is True
    assert NvidiaAdapter(api_key="k", model="meta/llama-3.2-90b-vision-instruct").supports_vision is True
    assert NvidiaAdapter(api_key="k", model="minimaxai/minimax-m3").supports_vision is False
    assert NvidiaAdapter(api_key="k", model="deepseek-ai/deepseek-v4-flash").supports_vision is False


def test_nvidia_adapter_default_model_is_top_tier(mocker):
    mocker.patch("llm.nvidia_adapter.OpenAI")
    from llm.nvidia_adapter import NvidiaAdapter
    a = NvidiaAdapter(api_key="k")
    assert a._model == "meta/llama-4-maverick-17b-128e-instruct"


def test_get_adapter_returns_nvidia_adapter(mocker):
    mock_adapter = mocker.patch("llm.nvidia_adapter.NvidiaAdapter")
    config = make_config("nvidia", nvidia_api_key="nvapi-test", nvidia_model="minimaxai/minimax-m3")
    get_llm_adapter(config)
    mock_adapter.assert_called_once_with(api_key="nvapi-test", model="minimaxai/minimax-m3")


def test_get_adapter_falls_back_to_ollama_when_provider_init_fails(mocker):
    """A missing/invalid API key makes the openai SDK raise immediately on
    client construction (both openai and nvidia adapters use it) — this must
    never crash the whole app at startup or on config save; Ollama (no key
    required) is the safe fallback."""
    mocker.patch("llm.nvidia_adapter.OpenAI", side_effect=RuntimeError("Missing credentials"))
    mock_ollama = mocker.patch("llm.ollama_adapter.OllamaAdapter")
    config = make_config(
        "nvidia", nvidia_api_key="", nvidia_model="deepseek-ai/deepseek-v4-pro",
        ollama_url="http://localhost:11434", ollama_model="llama3",
    )

    get_llm_adapter(config)

    mock_ollama.assert_called_once_with(url="http://localhost:11434", model="llama3")


def test_get_adapter_passes_ollama_url_and_model(mocker):
    mock_adapter = mocker.patch("llm.ollama_adapter.OllamaAdapter")
    config = make_config(
        "ollama",
        ollama_url="http://ollama.local:11434",
        ollama_model="mistral",
    )

    get_llm_adapter(config)

    mock_adapter.assert_called_once_with(
        url="http://ollama.local:11434",
        model="mistral",
    )


def test_openai_adapter_passes_max_tokens(mocker):
    """NVIDIA NIM (minimax-m3) returns an EMPTY choices list when max_tokens
    is omitted — the request must always carry an explicit budget."""
    from llm.openai_adapter import OpenAIAdapter
    adapter = OpenAIAdapter(api_key="k")
    mock_create = mocker.patch.object(
        adapter._client.chat.completions, "create",
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))]),
    )
    adapter.complete([{"role": "user", "content": "hi"}])
    assert mock_create.call_args.kwargs.get("max_tokens", 0) >= 1024
