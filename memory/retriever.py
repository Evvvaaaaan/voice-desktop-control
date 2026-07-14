import hashlib
import sys

from memory.embedder import Embedder
from memory.store import MemoryStore

# Keep the injected block small: it rides on EVERY command's system prompt.
MAX_BLOCK_CHARS = 800
MAX_PROFILE_KEYS = 15
MAX_HIT_CHARS = 200

_SOURCE_TAGS = {"daily_summary": "요약", "conversation": "이전 대화"}

# Vector search over past commands/conversations only fires when the
# command itself signals it needs past context — otherwise nearly every
# command pulls in an unrelated past command (short Korean commands cluster
# closely in embedding space) and the LLM can act on that instead of the
# actual request. Profile/pattern tiers stay unconditional: they're compact
# facts, not full past-command text, so they don't carry the same risk.
_MEMORY_CUES = (
    "기억", "저번", "예전", "아까", "지난번", "어제", "그저께", "지난주",
    "전에 말", "전에 했", "전에 얘기", "전에 물어",
    "내 이름", "내가 좋아하는", "내가 자주", "나에 대해", "내 정보", "내 취향",
)


def _needs_memory(query: str) -> bool:
    return any(cue in query for cue in _MEMORY_CUES)


class MemoryRetriever:
    """Builds the per-command memory block from tiers 1 (profile),
    5 (patterns), and 4 (vector search)."""

    def __init__(self, store: MemoryStore, embedder: Embedder | None, top_k: int = 3):
        self._store = store
        self._embedder = embedder
        self._top_k = top_k

    def build_memory_block(self, query: str) -> str | None:
        sections = self._stable_sections()

        hits = self._search(query)
        if hits:
            sections.append("관련 기억:\n" + "\n".join(hits))

        if not sections:
            return None
        return "\n\n".join(sections)[:MAX_BLOCK_CHARS]

    def fingerprint(self) -> str:
        """Content hash of the stable (profile + patterns) tiers. The agent
        drops its hot-command cache when this changes: a cached action is the
        model's interpretation of a command UNDER a specific memory state,
        and must not outlive it."""
        joined = "\n\n".join(self._stable_sections())
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()

    def _stable_sections(self) -> list[str]:
        """Query-independent tiers 1 (profile) and 5 (patterns)."""
        sections: list[str] = []

        profile = self._store.get_profile_ranked(MAX_PROFILE_KEYS)
        if profile:
            sections.append("프로필:\n" + "\n".join(f"- {k}: {v}" for k, v in profile))

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
        return sections

    def _search(self, query: str) -> list[str]:
        if self._embedder is None or not _needs_memory(query):
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
