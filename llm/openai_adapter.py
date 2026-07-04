import base64
from openai import OpenAI
from llm.base import LLMBase


class OpenAIAdapter(LLMBase):
    supports_vision = True

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        # Bounded timeout + capped retries so a stalled/unavailable endpoint
        # fails fast (→ spoken error) instead of hanging the command for
        # minutes; the SDK default (2 retries) would stack to ~3× the timeout.
        self._client = OpenAI(api_key=api_key, timeout=30.0, max_retries=1)
        self._model = model

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        # Always send an explicit token budget: NVIDIA NIM (e.g. minimax-m3,
        # served through this adapter) returns an empty choices list when
        # max_tokens is omitted.
        kwargs: dict = dict(model=self._model, messages=messages, max_tokens=4096)
        if tools:
            kwargs["tools"] = tools
        resp = self._client.chat.completions.create(**kwargs)
        if not resp.choices:
            raise RuntimeError(f"LLM returned no choices (model={self._model})")
        return resp.choices[0].message.content or ""

    def build_observation(self, text: str, screenshot_png: bytes) -> dict:
        b64 = base64.b64encode(screenshot_png).decode()
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }
