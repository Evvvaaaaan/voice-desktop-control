import requests
from llm.base import LLMBase


class OllamaAdapter(LLMBase):
    def __init__(self, url: str = "http://localhost:11434", model: str = "llama3"):
        self._url = url.rstrip("/")
        self._model = model

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        resp = requests.post(
            f"{self._url}/api/chat",
            json={"model": self._model, "messages": messages, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
