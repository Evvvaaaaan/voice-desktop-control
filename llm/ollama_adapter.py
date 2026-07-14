import base64
import requests
import sys
from llm.base import LLMBase


def _detect_vision_support(url: str, model: str) -> bool:
    """Ask Ollama's own /api/show for this model's capabilities instead of
    guessing from the model name. Name-based heuristics get this wrong on
    Ollama in both directions — e.g. this was tried with a substring check
    for "gemma3"/"gemma4", but /api/show reports "vision" for every gemma4
    tag including the small "e2b"/"e4b" variants (Gemma is natively
    multimodal at every size), while Ollama's own /api/tags listing omits
    "vision" for those exact same tags — so even a name-family match can't
    be trusted without checking the specific installed tag's capabilities.
    Falls back to False (same as any other unrecognized/text-only model) if
    Ollama isn't reachable yet or the model hasn't been pulled."""
    try:
        resp = requests.post(f"{url}/api/show", json={"model": model}, timeout=5)
        resp.raise_for_status()
        return "vision" in (resp.json().get("capabilities") or [])
    except Exception as e:
        print(f"[Ollama] Vision capability check failed for '{model}': {e}", file=sys.stderr)
        return False


# Ollama defaults num_ctx to a small window (2k/4k depending on version) and
# silently drops the OLDEST tokens when the prompt exceeds it — which cuts the
# system prompt (JSON format, tool rules) and the user's command first, so the
# model starts emitting arbitrary, unrelated actions with no error anywhere.
# The ReAct session (system prompt + history + per-step observations) needs an
# explicit window sized for it.
_NUM_CTX = 8192
# One decision is a single small JSON object. Weak local models that ignore
# "one object only" otherwise ramble for hundreds of tokens (pre-planned extra
# steps, prose) — on local hardware every extra token is pure latency, and the
# agent loop only reads the first JSON object anyway.
_NUM_PREDICT = 512
# With the default 5m keep_alive a pause between commands unloads the multi-GB
# model, and the next command pays a full reload (disk I/O storm + seconds of
# lag) before it can even start thinking.
_KEEP_ALIVE = "30m"


class OllamaAdapter(LLMBase):
    def __init__(self, url: str = "http://localhost:11434", model: str = "llama3"):
        self._url = url.rstrip("/")
        self._model = model
        self.supports_vision = _detect_vision_support(self._url, model)
        print(f"[Ollama] Initialized with URL={self._url}, Model={self._model}, "
              f"Vision={self.supports_vision}", file=sys.stderr)

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        print(f"[Ollama] Sending POST request to {self._url}/api/chat...", file=sys.stderr)
        print(f"[Ollama] Payload model: '{self._model}', Messages count: {len(messages)}", file=sys.stderr)
        try:
            resp = requests.post(
                f"{self._url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": False,
                    "options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT},
                    "keep_alive": _KEEP_ALIVE,
                },
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

    def build_observation(self, text: str, screenshot_png: bytes) -> dict:
        # Ollama's /api/chat takes images as a list of bare base64 strings
        # (no "data:image/...;base64," prefix, unlike the OpenAI-style adapters)
        # in an "images" field alongside "content".
        return {
            "role": "user",
            "content": text,
            "images": [base64.b64encode(screenshot_png).decode()],
        }
