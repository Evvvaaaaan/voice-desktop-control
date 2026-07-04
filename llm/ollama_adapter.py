import requests
import sys
from llm.base import LLMBase


class OllamaAdapter(LLMBase):
    def __init__(self, url: str = "http://localhost:11434", model: str = "llama3"):
        self._url = url.rstrip("/")
        self._model = model
        print(f"[Ollama] Initialized with URL={self._url}, Model={self._model}", file=sys.stderr)

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        print(f"[Ollama] Sending POST request to {self._url}/api/chat...", file=sys.stderr)
        print(f"[Ollama] Payload model: '{self._model}', Messages count: {len(messages)}", file=sys.stderr)
        try:
            resp = requests.post(
                f"{self._url}/api/chat",
                json={"model": self._model, "messages": messages, "stream": False},
                timeout=60,
            )
            print(f"[Ollama] HTTP Response status: {resp.status_code}", file=sys.stderr)
        except Exception as e:
            print(f"[Ollama] Connection/Timeout error: {e}", file=sys.stderr)
            raise

        if resp.status_code == 404:
            try:
                err_msg = resp.json().get("error", "")
                print(f"[Ollama] 404 JSON Error body: {err_msg}", file=sys.stderr)
                if "not found" in err_msg.lower():
                    raise RuntimeError(
                        f"Ollama 모델 '{self._model}'이 설치되어 있지 않습니다. "
                        f"터미널에서 'ollama pull {self._model}' 명령어를 실행하여 모델을 다운로드해 주세요."
                    )
            except (ValueError, KeyError):
                pass
        
        try:
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            print(f"[Ollama] Completed successfully. Response length: {len(content)} chars", file=sys.stderr)
            print(f"[Ollama] Raw LLM content:\n{content}\n-----------------", file=sys.stderr)
            return content
        except Exception as e:
            print(f"[Ollama] Failed to parse JSON or status was error: {e}", file=sys.stderr)
            print(f"[Ollama] Raw Response text: {resp.text}", file=sys.stderr)
            raise
