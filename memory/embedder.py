import sys

import requests

from llm.nvidia_adapter import NVIDIA_BASE_URL


class Embedder:
    """Text-embedding provider. embed() returns None on ANY failure so the
    vector tier degrades silently instead of breaking callers."""

    model: str = ""

    def embed(self, texts: list[str], kind: str = "passage") -> list[list[float]] | None:
        raise NotImplementedError


class OpenAICompatEmbedder(Embedder):
    def __init__(self, api_key: str, model: str, base_url: str | None = None,
                 needs_input_type: bool = False):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url=base_url,
                              timeout=15.0, max_retries=1)
        self.model = model
        self._needs_input_type = needs_input_type

    def embed(self, texts: list[str], kind: str = "passage") -> list[list[float]] | None:
        try:
            kwargs: dict = dict(model=self.model, input=texts)
            if self._needs_input_type:
                # NVIDIA nv-embedqa models reject requests without input_type;
                # plain OpenAI ignores unknown extra_body fields.
                kwargs["extra_body"] = {"input_type": kind, "truncate": "END"}
            resp = self._client.embeddings.create(**kwargs)
            return [d.embedding for d in resp.data]
        except Exception as e:
            print(f"[Memory] embedding failed ({e})", file=sys.stderr)
            return None


class OllamaEmbedder(Embedder):
    def __init__(self, url: str, model: str):
        self._url = url.rstrip("/")
        self.model = model

    def embed(self, texts: list[str], kind: str = "passage") -> list[list[float]] | None:
        try:
            out = []
            for text in texts:
                resp = requests.post(
                    f"{self._url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                    timeout=10,
                )
                if resp.status_code == 404:
                    # A bare "404 Not Found" (the default log line below)
                    # gives no clue that the fix is a single `ollama pull` —
                    # this is the single biggest reason vector-based memory
                    # search ("관련 기억") silently never contributes to a
                    # response: the chat model gets pulled, the SEPARATE
                    # embedding model doesn't.
                    try:
                        err_msg = resp.json().get("error", "")
                    except ValueError:
                        err_msg = ""
                    if "not found" in err_msg.lower():
                        print(
                            f"[Memory] Ollama 임베딩 모델 '{self.model}'이 설치되어 있지 않아 "
                            "과거 기록 기반 검색을 사용할 수 없습니다. 터미널에서 "
                            f"'ollama pull {self.model}' 실행 후 다시 시도하세요.",
                            file=sys.stderr,
                        )
                        return None
                resp.raise_for_status()
                out.append(resp.json()["embedding"])
            return out
        except Exception as e:
            print(f"[Memory] Ollama embedding failed ({e})", file=sys.stderr)
            return None


def get_embedder(config) -> Embedder | None:
    """Pick an embedding provider from config. Never raises and does no
    network I/O here; failures surface as embed() -> None at call time."""
    try:
        m = config.memory
        if not m.enabled or m.embedding_provider == "off":
            return None
        provider = m.embedding_provider
        if provider == "openai" or (provider == "auto" and config.llm.openai_api_key):
            return OpenAICompatEmbedder(config.llm.openai_api_key, m.openai_embedding_model)
        if provider == "nvidia" or (provider == "auto" and config.llm.nvidia_api_key):
            return OpenAICompatEmbedder(config.llm.nvidia_api_key, m.nvidia_embedding_model,
                                        base_url=NVIDIA_BASE_URL, needs_input_type=True)
        return OllamaEmbedder(config.llm.ollama_url, m.ollama_embedding_model)
    except Exception as e:
        print(f"[Memory] embedder init failed ({e})", file=sys.stderr)
        return None
