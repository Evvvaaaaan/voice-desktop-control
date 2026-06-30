import pytest
from unittest.mock import patch
from safety.guard import SafetyGuard


DANGEROUS_CASES = [
    ("delete_file", {"path": "/Users/evan/important.doc"}),
    ("run_applescript", {"script": "delete folder"}),
    ("run_applescript", {"script": "send email"}),
    ("run_applescript", {"script": "empty trash"}),
]

SAFE_CASES = [
    ("launch_app", {"app": "Safari"}),
    ("click", {"x": 100, "y": 200}),
    ("type_text", {"text": "hello"}),
    ("run_applescript", {"script": "tell application Safari to activate"}),
]


@pytest.mark.parametrize("action,params", DANGEROUS_CASES)
def test_detects_dangerous(action, params):
    guard = SafetyGuard(require_confirmation=True)
    assert guard.is_dangerous(action, params) is True


@pytest.mark.parametrize("action,params", SAFE_CASES)
def test_detects_safe(action, params):
    guard = SafetyGuard(require_confirmation=True)
    assert guard.is_dangerous(action, params) is False


def test_check_safe_action_proceeds_without_confirmation(mocker):
    mock_speak = mocker.patch("safety.guard.speak")
    guard = SafetyGuard(require_confirmation=True)
    result = guard.check("launch_app", {"app": "Safari"})
    assert result is True
    mock_speak.assert_not_called()


def test_check_dangerous_confirmed(mocker):
    mocker.patch("safety.guard.speak")
    mock_listen = mocker.patch("safety.guard._listen_for_confirmation", return_value="네")
    guard = SafetyGuard(require_confirmation=True)
    result = guard.check("delete_file", {"path": "/tmp/x"})
    assert result is True


def test_check_dangerous_declined(mocker):
    mocker.patch("safety.guard.speak")
    mocker.patch("safety.guard._listen_for_confirmation", return_value="아니오")
    guard = SafetyGuard(require_confirmation=True)
    result = guard.check("delete_file", {"path": "/tmp/x"})
    assert result is False


def test_confirmation_disabled_bypasses(mocker):
    mock_speak = mocker.patch("safety.guard.speak")
    guard = SafetyGuard(require_confirmation=False)
    result = guard.check("delete_file", {"path": "/tmp/x"})
    assert result is True
    mock_speak.assert_not_called()
