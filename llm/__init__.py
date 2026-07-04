from config.loader import Config
from llm.base import LLMBase


def get_llm_adapter(config: Config) -> LLMBase:
    provider = config.llm.provider
    if provider == "claude":
        from llm.claude_adapter import ClaudeAdapter
        return ClaudeAdapter(api_key=config.llm.claude_api_key, model=config.llm.claude_model)
    elif provider == "openai":
        from llm.openai_adapter import OpenAIAdapter
        return OpenAIAdapter(api_key=config.llm.openai_api_key, model=config.llm.openai_model)
    elif provider == "nvidia":
        from llm.nvidia_adapter import NvidiaAdapter
        return NvidiaAdapter(api_key=config.llm.nvidia_api_key, model=config.llm.nvidia_model)
    else:
        from llm.ollama_adapter import OllamaAdapter
        return OllamaAdapter(url=config.llm.ollama_url, model=config.llm.ollama_model)
