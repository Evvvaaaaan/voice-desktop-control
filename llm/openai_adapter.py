from openai import OpenAI
from llm.base import LLMBase


class OpenAIAdapter(LLMBase):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        kwargs: dict = dict(model=self._model, messages=messages)
        if tools:
            kwargs["tools"] = tools
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""
