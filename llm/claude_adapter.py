import anthropic
from llm.base import LLMBase


class ClaudeAdapter(LLMBase):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self._client = anthropic.Anthropic(api_key=api_key)
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
