from openai import OpenAI
from llm.openai_adapter import OpenAIAdapter

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


# NVIDIA NIM models known to accept image input, so the agent may feed
# screenshots (computer-use). Matched as substrings of the model id. Text-only
# models (e.g. minimax-m3, deepseek-v4-flash) hang on image blocks, so vision
# stays off for anything not listed here.
_VISION_MODELS = ("deepseek-v4-pro", "vision", "-vl-", "vl-", "-omni")


class NvidiaAdapter(OpenAIAdapter):
    """NVIDIA NIM (build.nvidia.com) — OpenAI-compatible endpoint, free API key.

    Reuses OpenAIAdapter's request/response handling since NIM speaks the same
    chat completions wire format; only the base_url and default model differ.
    Vision is enabled only for models known to be multimodal (see above), so
    computer-use (see-then-click) works on those and text-only models don't
    hang on image payloads.
    """

    def __init__(self, api_key: str, model: str = "deepseek-ai/deepseek-v4-pro"):
        self._client = OpenAI(api_key=api_key, base_url=NVIDIA_BASE_URL,
                              timeout=30.0, max_retries=1)
        self._model = model
        low = model.lower()
        self.supports_vision = any(v in low for v in _VISION_MODELS)
