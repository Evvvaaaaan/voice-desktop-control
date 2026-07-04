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


# ---------------------------------------------------------------------------
# Korean commands + shell-outs must trigger the danger check
# ---------------------------------------------------------------------------

def test_korean_delete_keyword_is_dangerous():
    guard = SafetyGuard()
    assert guard.is_dangerous("type_text", {"text": "파일 전부 삭제해줘"}) is True
    assert guard.is_dangerous("run_applescript", {"script": "휴지통 비우기"}) is True


def test_applescript_shell_out_is_dangerous():
    guard = SafetyGuard()
    assert guard.is_dangerous(
        "run_applescript", {"script": 'do shell script "rm -rf ~/tmp"'}
    ) is True


def test_benign_korean_params_not_dangerous():
    guard = SafetyGuard()
    assert guard.is_dangerous("type_text", {"text": "안녕하세요 반갑습니다"}) is False
    assert guard.is_dangerous("launch_app", {"app": "Safari"}) is False


# ---------------------------------------------------------------------------
# HUD-button confirmation (ConfirmDecision)
# ---------------------------------------------------------------------------

from safety.guard import ConfirmDecision


def test_confirm_decision_first_resolution_wins():
    d = ConfirmDecision()
    d.resolve(True)
    d.resolve(False)                     # late answer ignored
    assert d.wait(0.01) is True


def test_confirm_decision_times_out_to_none():
    d = ConfirmDecision()
    assert d.wait(0.01) is None


def test_hud_button_confirms_without_voice(mocker):
    """Clicking 실행 resolves the check even when voice hears nothing."""
    mocker.patch("safety.guard.speak")
    mocker.patch("safety.guard._listen_for_confirmation", return_value="")
    armed = {}
    guard = SafetyGuard(require_confirmation=True,
                        ui_confirm=lambda d: armed.setdefault("d", d).resolve(True))
    assert guard.check("delete_file", {"path": "/tmp/x"}) is True
    assert "d" in armed


def test_hud_button_denies_without_voice(mocker):
    mocker.patch("safety.guard.speak")
    mocker.patch("safety.guard._listen_for_confirmation", return_value="")
    guard = SafetyGuard(require_confirmation=True,
                        ui_confirm=lambda d: d.resolve(False))
    assert guard.check("delete_file", {"path": "/tmp/x"}) is False


def test_no_answer_times_out_to_deny(mocker):
    mocker.patch("safety.guard.speak")
    mocker.patch("safety.guard._listen_for_confirmation", return_value="")
    mocker.patch("safety.guard._CONFIRM_TIMEOUT_SEC", 0.05)
    guard = SafetyGuard(require_confirmation=True)
    assert guard.check("delete_file", {"path": "/tmp/x"}) is False
