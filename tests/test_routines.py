import pytest
import json
from routines.detector import RoutineDetector
from routines.manager import RoutineManager


@pytest.fixture
def detector(tmp_path):
    return RoutineDetector(str(tmp_path / "test.db"), threshold=3)


@pytest.fixture
def manager(tmp_path):
    return RoutineManager(str(tmp_path / "routines.json"))


def test_detector_returns_false_below_threshold(detector):
    assert detector.record("사파리 열어줘") is False
    assert detector.record("사파리 열어줘") is False


def test_detector_returns_true_at_threshold(detector):
    detector.record("사파리 열어줘")
    detector.record("사파리 열어줘")
    assert detector.record("사파리 열어줘") is True


def test_detector_resets_after_threshold(detector):
    for _ in range(3):
        detector.record("cmd")
    assert detector.record("cmd") is False


def test_manager_save_and_load(manager):
    steps = [{"action": "launch_app", "params": {"app": "Safari"}}]
    manager.save("웹 열기", steps)
    routines = manager.load_all()
    assert len(routines) == 1
    assert routines[0]["name"] == "웹 열기"
    assert routines[0]["steps"] == steps


def test_manager_execute(manager, mocker):
    steps = [{"action": "launch_app", "params": {"app": "Safari"}}]
    manager.save("웹 열기", steps)
    mock_executor = mocker.MagicMock()
    mock_executor.run.return_value = True
    result = manager.execute("웹 열기", mock_executor)
    assert result is True
    mock_executor.run.assert_called_once_with("launch_app", {"app": "Safari"})
