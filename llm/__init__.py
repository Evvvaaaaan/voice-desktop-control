import sys
from config.loader import Config
from llm.base import LLMBase


def get_llm_adapter(config: Config) -> LLMBase:
    provider = config.llm.provider
    try:
        if provider == "claude":
            from llm.claude_adapter import ClaudeAdapter
            return ClaudeAdapter(api_key=config.llm.claude_api_key, model=config.llm.claude_model)
        elif provider == "openai":
            from llm.openai_adapter import OpenAIAdapter
            return OpenAIAdapter(api_key=config.llm.openai_api_key, model=config.llm.openai_model)
        elif provider == "nvidia":
            from llm.nvidia_adapter import NvidiaAdapter
            return NvidiaAdapter(api_key=config.llm.nvidia_api_key, model=config.llm.nvidia_model)
    except Exception as e:
        # A missing/invalid API key makes the OpenAI SDK (used by both the
        # openai and nvidia adapters) raise immediately on client
        # construction — this call runs at app startup and on every config
        # save, so letting it propagate crashes the whole app instead of
        # just failing the next command. Fall back to Ollama (no key
        # needed) so the app stays usable; the user fixes the key in
        # Settings (which now links straight to each provider's key page).
        print(f"[LLM] {provider} adapter init failed ({e}); falling back to Ollama. "
              "설정에서 API 키를 확인해 주세요.", file=sys.stderr)

    from llm.ollama_adapter import OllamaAdapter
    return OllamaAdapter(url=config.llm.ollama_url, model=config.llm.ollama_model)
