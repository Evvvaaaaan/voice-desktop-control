import json
import re
import sys
import threading
from collections import Counter
from datetime import datetime

from llm.base import LLMBase
from memory.embedder import Embedder
from memory.patterns import compute_patterns
from memory.store import MemoryStore

# This prompt belongs to the offline daily-summary job, NOT the agent loop —
# the CLAUDE.md rule pins only the AGENT system prompt to agent/context.py.
SUMMARY_PROMPT = """You are summarizing one day of a Korean voice-assistant user's activity.
Given the day's conversation turns and an action digest, respond with ONLY a
single JSON object — no prose, no markdown fences:
{"summary": "<한국어 요약 3-6문장: 무엇을 했고, 무엇에 관심을 보였는지>",
 "profile_facts": [{"key": "<snake_case_english_key>", "value": "<value>", "confidence": <0.0-1.0>}]}

profile_facts are slowly-changing facts about the USER themselves (name, job,
sleep schedule, preferred tools/IDE, hobbies) explicitly evidenced in the
conversations. Do NOT invent facts; return [] when nothing qualifies."""

_JSON_RE = re.compile(r'\{.*\}', re.DOTALL)
_THINK_BLOCK_RE = re.compile(r'<think>.*?</think>', re.DOTALL)

MAX_TURNS_PER_DAY = 100
MAX_TURN_CHARS = 300
EMBED_BATCH = 32


def _strip_think(raw: str) -> str:
    cleaned = _THINK_BLOCK_RE.sub("", raw)
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1]
    return cleaned


class DailySummarizer:
    """Turns past days' logs into tier-3 summaries, tier-1 profile facts,
    tier-4 vectors, and refreshed tier-5 patterns."""

    def __init__(self, store: MemoryStore, llm: LLMBase, embedder: Embedder | None):
        self._store = store
        self._llm = llm
        self._embedder = embedder

    def start_background(self) -> threading.Thread:
        thread = threading.Thread(target=self._run_safe, daemon=True,
                                  name="voicedesk-memory-summarizer")
        thread.start()
        return thread

    def _run_safe(self) -> None:
        try:
            self.run_pending()
        except Exception as e:
            print(f"[Memory] summarizer thread failed: {e}", file=sys.stderr)

    def run_pending(self) -> None:
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        for day in self._store.unsummarized_days(today, limit=7):
            try:
                self.summarize_day(day)
            except Exception as e:
                print(f"[Memory] summarizing {day} failed: {e}", file=sys.stderr)
        try:
            patterns = compute_patterns(self._store)
            if patterns:
                self._store.set_patterns(patterns)
        except Exception as e:
            print(f"[Memory] pattern refresh failed: {e}", file=sys.stderr)
        self.embed_backlog()

    def summarize_day(self, day: str) -> None:
        turns = self._store.get_day_conversations(day)[:MAX_TURNS_PER_DAY]
        behavior = self._store.get_day_behavior(day)
        if not turns and not behavior:
            return

        lines = [f"[{day}] 대화 기록:"]
        for _, user_text, assistant_text in turns:
            lines.append(f"사용자: {user_text[:MAX_TURN_CHARS]}")
            lines.append(f"비서: {assistant_text[:MAX_TURN_CHARS]}")
        digest = Counter(f"{a}:{t}" if t else a for a, t, _ in behavior)
        if digest:
            lines.append("동작 요약: " + ", ".join(
                f"{k}×{n}" for k, n in digest.most_common(15)))

        raw = self._llm.complete([
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ])

        summary, facts = self._parse(raw)
        self._store.add_daily_summary(day, summary)
        for fact in facts:
            try:
                key, value = str(fact["key"]).strip(), str(fact["value"]).strip()
                confidence = float(fact.get("confidence", 0))
            except (KeyError, TypeError, ValueError):
                continue
            if key and value and confidence >= 0.6:
                self._store.set_profile(key, value, source="auto", confidence=confidence)

    @staticmethod
    def _parse(raw: str) -> tuple[str, list[dict]]:
        """Extract (summary, profile_facts) from the LLM reply. On parse
        failure the raw text becomes the summary so the day never re-loops."""
        cleaned = _strip_think(raw).strip()
        match = _JSON_RE.search(cleaned)
        if match:
            try:
                data = json.loads(match.group(0))
                summary = str(data.get("summary", "")).strip()
                facts = data.get("profile_facts", [])
                if summary:
                    return summary, facts if isinstance(facts, list) else []
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        return cleaned or "(요약 실패)", []

    def embed_backlog(self) -> None:
        """Embed conversation/summary rows that have no vector yet. A day
        summarized while offline gets its vectors on a later launch."""
        if self._embedder is None:
            return
        for source_type in ("daily_summary", "conversation"):
            rows = self._store.rows_missing_vectors(source_type)
            for start in range(0, len(rows), EMBED_BATCH):
                batch = rows[start:start + EMBED_BATCH]
                vectors = self._embedder.embed([content for _, content in batch])
                if vectors is None:
                    return
                for (source_id, content), vec in zip(batch, vectors):
                    self._store.add_vector(source_type, source_id, content,
                                           vec, self._embedder.model)
