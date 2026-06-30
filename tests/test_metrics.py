import pytest
import tempfile
import os
from metrics.collector import MetricsCollector
from metrics.aggregator import get_today_summary


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def test_record_and_retrieve(db_path):
    collector = MetricsCollector(db_path)
    collector.record(
        command="사파리 열어줘",
        stt_confidence=0.95,
        success=True,
        retry_count=0,
        dangerous=False,
        response_ms=1200,
        is_repeated=False,
    )
    summary = get_today_summary(db_path)
    assert summary["success_rate"] == 1.0
    assert summary["avg_response_ms"] == 1200
    assert summary["dangerous_count"] == 0


def test_recognition_rate(db_path):
    collector = MetricsCollector(db_path)
    collector.record("cmd", 0.98, True, 0, False, 800, False)
    collector.record("cmd", 0.45, False, 1, False, 2000, False)
    summary = get_today_summary(db_path)
    assert summary["recognition_rate"] == 0.5


def test_repeated_count(db_path):
    collector = MetricsCollector(db_path)
    for _ in range(3):
        collector.record("cmd", 0.9, True, 0, False, 500, True)
    summary = get_today_summary(db_path)
    assert summary["repeated_count"] == 3


def test_dangerous_count(db_path):
    collector = MetricsCollector(db_path)
    collector.record("delete", 0.9, True, 0, True, 1000, False)
    collector.record("safe", 0.9, True, 0, False, 800, False)
    summary = get_today_summary(db_path)
    assert summary["dangerous_count"] == 1
