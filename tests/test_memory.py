import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from config.loader import Config, MemoryConfig, LLMConfig
from memory.store import MemoryStore
from memory.embedder import (
    Embedder,
    OllamaEmbedder,
    OpenAICompatEmbedder,
    get_embedder,
)
from memory.patterns import compute_patterns
from memory.retriever import MemoryRetriever
from memory.summarizer import DailySummarizer


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def store(db_path):
    return MemoryStore(db_path)


class FakeEmbedder(Embedder):
    """Deterministic 3-dim vectors: text hash spread over axes."""

    model = "fake"

    def embed(self, texts, kind="passage"):
        out = []
        for t in texts:
            h = sum(ord(c) for c in t)  # deterministic across processes
            out.append([1.0 + h % 7, 1.0 + h % 11, 1.0 + h % 13])
        return out


def _backdate(db, table, days):
    """Shift every row's timestamp back by `days` days."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute(f"UPDATE {table} SET timestamp=?", (ts,))


# ---------- MemoryStore ----------

def test_store_ddl_idempotent(db_path):
    MemoryStore(db_path)
    MemoryStore(db_path)  # second init on same file must not raise


def test_profile_upsert_and_get(store):
    store.set_profile("name", "하민", source="auto", confidence=0.9)
    store.set_profile("name", "박하민", source="auto", confidence=0.95)
    assert store.get_profile() == {"name": "박하민"}


def test_profile_auto_never_overwrites_user(store):
    store.set_profile("preferred_ide", "VSCode", source="user")
    store.set_profile("preferred_ide", "IntelliJ", source="auto", confidence=0.99)
    assert store.get_profile()["preferred_ide"] == "VSCode"
    # user CAN overwrite user
    store.set_profile("preferred_ide", "Vim", source="user")
    assert store.get_profile()["preferred_ide"] == "Vim"
    # and user overwrites auto
    store.set_profile("job", "학생", source="auto")
    store.set_profile("job", "개발자", source="user")
    assert store.get_profile()["job"] == "개발자"


def test_delete_profile(store):
    store.set_profile("name", "하민")
    store.delete_profile("name")
    assert store.get_profile() == {}


def test_profile_ranked_puts_user_facts_and_confidence_first(store):
    store.set_profile("aa_auto_low", "x", source="auto", confidence=0.6)
    store.set_profile("bb_auto_high", "y", source="auto", confidence=0.9)
    store.set_profile("zz_user", "하민", source="user")
    assert store.get_profile_ranked(2) == [("zz_user", "하민"), ("bb_auto_high", "y")]


def test_embeddable_column_migrated_on_old_db(db_path):
    # A DB created before the embeddable column existed must be upgraded
    # in place on the next launch.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE long_term_memory ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL UNIQUE, "
            "summary TEXT NOT NULL, created_at TEXT NOT NULL)")
    store = MemoryStore(db_path)
    store.add_daily_summary("2026-07-01", "요약")
    store.add_daily_summary("2026-07-02", "파싱 실패 원문", embeddable=False)
    assert store.rows_missing_vectors("daily_summary") == [(1, "요약")]


def test_behavior_and_conversation_roundtrip(store, db_path):
    store.log_action("크롬 열어줘", "launch_app", "Google Chrome", True, "{}")
    store.log_command("크롬 열어줘", True, 1200)
    row_id = store.log_conversation("크롬 열어줘", "크롬을 열었어요.")
    assert row_id == 1
    with sqlite3.connect(db_path) as conn:
        actions = conn.execute(
            "SELECT event_type, action, target, success FROM behavior_log ORDER BY id"
        ).fetchall()
        convs = conn.execute(
            "SELECT user_text, assistant_text FROM conversation_log"
        ).fetchall()
    assert actions == [("action", "launch_app", "Google Chrome", 1),
                       ("command", None, None, 1)]
    assert convs == [("크롬 열어줘", "크롬을 열었어요.")]


def test_unsummarized_days_excludes_today_and_done(store, db_path):
    store.log_conversation("어제 명령", "응답")
    _backdate(db_path, "conversation_log", 1)
    store.log_command("오늘 명령", True, 100)   # today — must be excluded
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    yesterday = (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")

    assert store.unsummarized_days(today) == [yesterday]
    store.add_daily_summary(yesterday, "요약")
    assert store.unsummarized_days(today) == []


def test_vector_roundtrip_and_search(store):
    emb = FakeEmbedder()
    for i, text in enumerate(["크롬으로 논문 검색", "유튜브 음악 재생", "메일 확인"]):
        store.add_vector("conversation", i + 1, text, emb.embed([text])[0], "fake")
    query_vec = emb.embed(["크롬으로 논문 검색"])[0]
    results = store.search_vectors(query_vec, "fake", top_k=2, min_sim=0.0)
    assert results[0][2] == "크롬으로 논문 검색"
    assert results[0][0] == pytest.approx(1.0)
    # model mismatch returns nothing
    assert store.search_vectors(query_vec, "other-model") == []


def test_search_vectors_default_threshold_drops_weak_matches(store):
    # Loosely-related content (cosine < 0.5) must not resurface as a
    # "관련 기억" — short Korean commands cluster closely in embedding space.
    store.add_vector("conversation", 1, "강한 관련", [1.0, 0.1, 0.0], "fake")
    store.add_vector("conversation", 2, "약한 관련", [0.44, 0.9, 0.0], "fake")
    results = store.search_vectors([1.0, 0.0, 0.0], "fake")
    assert [content for _, _, content in results] == ["강한 관련"]


def test_rows_missing_vectors(store):
    cid = store.log_conversation("안녕", "안녕하세요")
    sid = store.add_daily_summary("2026-07-01", "하루 요약")
    assert store.rows_missing_vectors("conversation") == [(cid, "안녕 / 안녕하세요")]
    assert store.rows_missing_vectors("daily_summary") == [(sid, "하루 요약")]
    store.add_vector("conversation", cid, "안녕", [1.0, 0.0], "fake")
    assert store.rows_missing_vectors("conversation") == []


def test_patterns_roundtrip(store):
    store.set_patterns({"top_apps": [["Chrome", 3]], "avg_commands_per_day": 2.5})
    assert store.get_patterns() == {"top_apps": [["Chrome", 3]],
                                    "avg_commands_per_day": 2.5}


# ---------- Embedder selection ----------

def _config(provider="auto", openai_key="", nvidia_key=""):
    cfg = Config()
    cfg.memory = MemoryConfig(embedding_provider=provider)
    cfg.llm = LLMConfig(openai_api_key=openai_key, nvidia_api_key=nvidia_key)
    return cfg


def test_get_embedder_off_and_disabled():
    assert get_embedder(_config(provider="off")) is None
    cfg = _config()
    cfg.memory.enabled = False
    assert get_embedder(cfg) is None


def test_get_embedder_auto_prefers_openai_then_nvidia():
    assert isinstance(get_embedder(_config(openai_key="sk-x", nvidia_key="nv-x")),
                      OpenAICompatEmbedder)
    emb = get_embedder(_config(nvidia_key="nv-x"))
    assert isinstance(emb, OpenAICompatEmbedder)
    assert emb._needs_input_type is True


def test_get_embedder_auto_falls_back_to_ollama():
    emb = get_embedder(_config())
    assert isinstance(emb, OllamaEmbedder)


def test_ollama_embedder_returns_none_on_connection_error(mocker):
    mocker.patch("memory.embedder.requests.post", side_effect=ConnectionError("down"))
    emb = OllamaEmbedder("http://localhost:11434", "nomic-embed-text")
    assert emb.embed(["hello"]) is None


def test_ollama_embedder_success(mocker):
    resp = MagicMock()
    resp.json.return_value = {"embedding": [0.1, 0.2]}
    mocker.patch("memory.embedder.requests.post", return_value=resp)
    emb = OllamaEmbedder("http://localhost:11434", "nomic-embed-text")
    assert emb.embed(["a", "b"]) == [[0.1, 0.2], [0.1, 0.2]]


def test_ollama_embedder_missing_model_logs_actionable_hint(mocker, capsys):
    """A bare '404 Client Error: Not Found' gives no clue the fix is a single
    `ollama pull` — the single biggest reason vector-based memory search
    silently never contributes to a response (the chat model gets pulled,
    the separate embedding model doesn't)."""
    resp = MagicMock(status_code=404)
    resp.json.return_value = {"error": "model 'nomic-embed-text' not found, try pulling it first"}
    mocker.patch("memory.embedder.requests.post", return_value=resp)
    emb = OllamaEmbedder("http://localhost:11434", "nomic-embed-text")

    result = emb.embed(["hello"])

    assert result is None
    err = capsys.readouterr().err
    assert "ollama pull nomic-embed-text" in err


# ---------- Patterns ----------

def test_compute_patterns_empty(store):
    assert compute_patterns(store) == {}


def test_compute_patterns_aggregates(store):
    for _ in range(3):
        store.log_action("크롬 열어줘", "launch_app", "Google Chrome", True)
        store.log_command("크롬 열어줘", True, 100)
    store.log_action("사파리 열어줘", "launch_app", "Safari", True)
    store.log_command("메일 확인해줘", True, 100)

    patterns = compute_patterns(store)
    assert patterns["top_apps"][0] == ["Google Chrome", 3]
    assert patterns["top_commands"][0] == ["크롬 열어줘", 3]
    assert sum(patterns["active_hours"].values()) == 4
    assert patterns["avg_commands_per_day"] == 4.0


# ---------- DailySummarizer ----------

def _summary_json(summary="어제는 크롬으로 논문을 검색했다.", facts=None):
    return json.dumps({"summary": summary, "profile_facts": facts or []},
                      ensure_ascii=False)


def _seed_yesterday(store, db_path):
    store.log_conversation("크롬 열어줘", "크롬을 열었어요.")
    store.log_action("크롬 열어줘", "launch_app", "Google Chrome", True)
    _backdate(db_path, "conversation_log", 1)
    _backdate(db_path, "behavior_log", 1)
    return (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")


def test_summarizer_writes_summary_facts_and_vectors(store, db_path):
    yesterday = _seed_yesterday(store, db_path)
    mock_llm = MagicMock()
    mock_llm.complete.return_value = _summary_json(
        facts=[{"key": "preferred_browser", "value": "Chrome", "confidence": 0.8},
               {"key": "low_conf", "value": "x", "confidence": 0.3}])

    DailySummarizer(store, mock_llm, FakeEmbedder()).run_pending()

    assert dict(store.get_recent_summaries())[yesterday] == "어제는 크롬으로 논문을 검색했다."
    profile = store.get_profile()
    assert profile == {"preferred_browser": "Chrome"}  # low-confidence fact dropped
    # summary + conversation embedded
    assert store.rows_missing_vectors("daily_summary") == []
    assert store.rows_missing_vectors("conversation") == []
    # patterns refreshed from behavior log
    assert store.get_patterns()["top_apps"][0] == ["Google Chrome", 1]


def test_summarizer_garbage_reply_stores_raw_no_facts(store, db_path):
    yesterday = _seed_yesterday(store, db_path)
    mock_llm = MagicMock()
    mock_llm.complete.return_value = "그냥 텍스트 응답"

    DailySummarizer(store, mock_llm, None).run_pending()

    assert dict(store.get_recent_summaries())[yesterday] == "그냥 텍스트 응답"
    assert store.get_profile() == {}
    # day is summarized → never re-loops
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    assert store.unsummarized_days(today) == []


def test_summarizer_failed_parse_summary_never_embedded(store, db_path):
    _seed_yesterday(store, db_path)
    mock_llm = MagicMock()
    mock_llm.complete.return_value = "그냥 텍스트 응답"

    DailySummarizer(store, mock_llm, FakeEmbedder()).run_pending()

    # the raw junk is stored as the summary (day never re-loops) but must
    # never enter the vector store, where it would resurface as a memory hit
    assert store.rows_missing_vectors("daily_summary") == []
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT content FROM memory_vectors "
                            "WHERE source_type='daily_summary'").fetchall()
    assert rows == []


def test_summarizer_llm_failure_keeps_day_pending(store, db_path):
    yesterday = _seed_yesterday(store, db_path)
    mock_llm = MagicMock()
    mock_llm.complete.side_effect = RuntimeError("connection refused")

    DailySummarizer(store, mock_llm, None).run_pending()  # must not raise

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    assert store.unsummarized_days(today) == [yesterday]


def test_summarizer_strips_think_block(store, db_path):
    _seed_yesterday(store, db_path)
    mock_llm = MagicMock()
    mock_llm.complete.return_value = (
        "<think>reasoning...</think>" + _summary_json(summary="요약본"))

    DailySummarizer(store, mock_llm, None).run_pending()
    assert store.get_recent_summaries()[0][1] == "요약본"


def test_summarizer_loop_reruns_until_stopped(store):
    """Patterns (and day rollovers) must refresh while the app stays up —
    a single pass at launch would freeze hourly_commands for the suggester."""
    summarizer = DailySummarizer(store, MagicMock(), None, refresh_interval_sec=0)
    calls = []

    def fake_run_pending():
        calls.append(1)
        if len(calls) == 2:
            summarizer.stop()

    summarizer.run_pending = fake_run_pending
    summarizer._loop()  # returns because stop() fired on the second pass
    assert len(calls) == 2


def test_summarizer_loop_survives_a_failing_pass(store):
    summarizer = DailySummarizer(store, MagicMock(), None, refresh_interval_sec=0)
    calls = []

    def fake_run_pending():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("llm down")
        summarizer.stop()

    summarizer.run_pending = fake_run_pending
    summarizer._loop()  # first pass fails, loop keeps going
    assert len(calls) == 2


# ---------- MemoryRetriever ----------

def test_retriever_profile_only_without_embedder(store):
    store.set_profile("name", "하민", source="user")
    block = MemoryRetriever(store, None).build_memory_block("아무 명령")
    assert "- name: 하민" in block
    assert "관련 기억" not in block


def test_retriever_profile_survives_junk_key_flood(store):
    # Alphabetically-early auto-extracted keys used to crowd a user-entered
    # fact out of the injected block entirely (old code sliced get_profile()
    # in key order); ranking is by source/confidence/recency now.
    for i in range(20):
        store.set_profile(f"aa_junk_{i:02d}", "x", source="auto", confidence=0.6)
    store.set_profile("zz_name", "하민", source="user")
    block = MemoryRetriever(store, None).build_memory_block("아무 명령")
    assert "- zz_name: 하민" in block


def test_retriever_fingerprint_tracks_stable_tiers(store):
    retriever = MemoryRetriever(store, None)
    fp_empty = retriever.fingerprint()
    assert fp_empty == retriever.fingerprint()  # deterministic
    store.set_profile("name", "하민", source="user")
    fp_profile = retriever.fingerprint()
    assert fp_profile != fp_empty
    store.set_patterns({"top_apps": [["Chrome", 5]]})
    assert retriever.fingerprint() != fp_profile


def test_retriever_includes_vector_hits(store):
    emb = FakeEmbedder()
    text = "어제 크롬으로 논문을 검색했다"
    store.add_vector("daily_summary", 1, text, emb.embed([text])[0], "fake")
    block = MemoryRetriever(store, emb).build_memory_block(text)
    assert f"[요약] {text}" in block


def test_retriever_skips_vector_search_without_memory_cue(store):
    # A command with no reference to past context must not pull in an
    # unrelated past command/summary, even if the embedder finds a match.
    emb = FakeEmbedder()
    text = "크롬으로 논문을 검색했다"
    store.add_vector("daily_summary", 1, text, emb.embed([text])[0], "fake")
    block = MemoryRetriever(store, emb).build_memory_block("크롬 열어줘")
    assert block is None


def test_retriever_vector_search_fires_on_memory_cue(store):
    emb = FakeEmbedder()
    text = "크롬으로 논문을 검색했다"
    store.add_vector("daily_summary", 1, text, emb.embed([text])[0], "fake")
    block = MemoryRetriever(store, emb).build_memory_block("저번에 크롬으로 뭐 검색했지?")
    assert f"[요약] {text}" in block


def test_retriever_empty_store_returns_none(store):
    assert MemoryRetriever(store, None).build_memory_block("명령") is None


def test_retriever_includes_patterns(store):
    store.set_patterns({"top_apps": [["Chrome", 5], ["Safari", 2]],
                        "active_hours": {"21": 10, "9": 3}})
    block = MemoryRetriever(store, None).build_memory_block("명령")
    assert "자주 쓰는 앱: Chrome, Safari" in block
    assert "21시" in block


# ---------- ConversationContext memory block ----------

def test_context_merges_memory_block_into_single_system_message():
    from agent.context import ConversationContext, SYSTEM_PROMPT
    ctx = ConversationContext()
    messages = ctx.to_messages("명령", memory_block="- name: 하민")
    systems = [m for m in messages if m["role"] == "system"]
    assert len(systems) == 1
    assert SYSTEM_PROMPT in systems[0]["content"]
    assert "- name: 하민" in systems[0]["content"]
    # without a block the output is unchanged
    assert ctx.to_messages("명령")[0]["content"] == SYSTEM_PROMPT


def test_context_memory_block_carries_strict_usage_rules():
    from agent.context import ConversationContext
    ctx = ConversationContext()
    content = ctx.to_messages("명령", memory_block="- name: 하민")[0]["content"]
    assert "Memory rules (STRICT)" in content
    assert "NEVER change an app, site, URL, or target" in content
    # rules only ride along WITH a memory block
    assert "Memory rules" not in ctx.to_messages("명령")[0]["content"]


# ---------- hourly_commands pattern ----------

def _insert_command_at(db_path, command, days_ago, hour):
    """Insert a behavior_log command row at a specific local day/hour."""
    local = (datetime.now().astimezone() - timedelta(days=days_ago)).replace(
        hour=hour, minute=0, second=0, microsecond=0)
    ts = local.astimezone(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO behavior_log VALUES (NULL,?,?,?,?,?,?,?)",
            (ts, "command", command, None, None, 1, "{}"),
        )


def test_compute_patterns_hourly_commands(store, db_path):
    for days_ago in (1, 2, 3):
        _insert_command_at(db_path, "크롬 열어줘", days_ago, 9)
    patterns = compute_patterns(store)
    assert patterns["hourly_commands"]["9"][0] == ["크롬 열어줘", 3]


def test_compute_patterns_hourly_excludes_single_day_burst(store, db_path):
    for _ in range(4):
        _insert_command_at(db_path, "유튜브 틀어줘", 1, 21)
    patterns = compute_patterns(store)
    assert "21" not in patterns.get("hourly_commands", {})


# ---------- suggestion_log store helpers ----------

def test_suggestion_log_roundtrip_and_last_at(store):
    assert store.last_suggestion_at() is None
    store.log_suggestion("크롬 열어줘", 9, "accepted")
    store.log_suggestion("메일 확인해줘", 10, "timeout")
    last = store.last_suggestion_at()
    assert last is not None
    assert datetime.fromisoformat(last).hour == datetime.now(timezone.utc).hour


def test_suggestion_declined_on_matches_day_and_key(store, db_path):
    store.log_suggestion("크롬 열어줘", 9, "declined")
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    yesterday = (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert store.suggestion_declined_on("크롬 열어줘", today) is True
    assert store.suggestion_declined_on("크롬 열어줘", yesterday) is False
    assert store.suggestion_declined_on("다른 명령", today) is False
    # survives a restart (new MemoryStore over the same file)
    assert MemoryStore(db_path).suggestion_declined_on("크롬 열어줘", today) is True
    # accepted/timeout outcomes don't suppress
    store.log_suggestion("메일 확인해줘", 9, "timeout")
    assert store.suggestion_declined_on("메일 확인해줘", today) is False


def test_command_seen_since(store):
    store.log_command("크롬 열어줘", True, 100)
    hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    just_now = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    assert store.command_seen_since("크롬 열어줘", hour_ago) is True
    assert store.command_seen_since("크롬 열어줘", just_now) is False
    assert store.command_seen_since("다른 명령", hour_ago) is False
