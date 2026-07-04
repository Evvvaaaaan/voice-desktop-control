import base64
import anthropic
from llm.base import LLMBase


class ClaudeAdapter(LLMBase):
    supports_vision = True

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self._client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=1)
        self._model = model

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        kwargs: dict = dict(
            model=self._model,
            max_tokens=1024,
            messages=user_msgs,
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        msg = self._client.messages.create(**kwargs)
        for block in msg.content:
            if block.type == "text":
                return block.text
        return ""

    def build_observation(self, text: str, screenshot_png: bytes) -> dict:
        b64 = base64.b64encode(screenshot_png).decode()
        return {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": text},
            ],
        }
