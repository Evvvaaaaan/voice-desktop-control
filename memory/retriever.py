import sys

from memory.embedder import Embedder
from memory.store import MemoryStore

# Keep the injected block small: it rides on EVERY command's system prompt.
MAX_BLOCK_CHARS = 800
MAX_PROFILE_KEYS = 15
MAX_HIT_CHARS = 200

_SOURCE_TAGS = {"daily_summary": "요약", "conversation": "이전 대화"}


class MemoryRetriever:
    """Builds the per-command memory block from tiers 1 (profile),
    5 (patterns), and 4 (vector search)."""

    def __init__(self, store: MemoryStore, embedder: Embedder | None, top_k: int = 3):
        self._store = store
        self._embedder = embedder
        self._top_k = top_k

    def build_memory_block(self, query: str) -> str | None:
        sections: list[str] = []

        profile = self._store.get_profile()
        if profile:
            items = list(profile.items())[:MAX_PROFILE_KEYS]
            sections.append("프로필:\n" + "\n".join(f"- {k}: {v}" for k, v in items))

        patterns = self._store.get_patterns()
        pattern_lines = []
        top_apps = patterns.get("top_apps")
        if top_apps:
            pattern_lines.append("자주 쓰는 앱: " + ", ".join(a for a, _ in top_apps[:3]))
        active_hours = patterns.get("active_hours")
        if active_hours:
            peak = sorted(active_hours.items(), key=lambda kv: kv[1], reverse=True)[:2]
            pattern_lines.append("주 활동 시간대: " + ", ".join(f"{h}시" for h, _ in peak))
        if pattern_lines:
            sections.append("사용 패턴:\n" + "\n".join(f"- {line}" for line in pattern_lines))

        hits = self._search(query)
        if hits:
            sections.append("관련 기억:\n" + "\n".join(hits))

        if not sections:
            return None
        return "\n\n".join(sections)[:MAX_BLOCK_CHARS]

    def _search(self, query: str) -> list[str]:
        if self._embedder is None:
            return []
        vectors = self._embedder.embed([query], kind="query")
        if not vectors:
            return []
        results = self._store.search_vectors(vectors[0], self._embedder.model,
                                             top_k=self._top_k)
        lines = []
        for _sim, source_type, content in results:
            tag = _SOURCE_TAGS.get(source_type, source_type)
            lines.append(f"- [{tag}] {content[:MAX_HIT_CHARS]}")
        return lines
