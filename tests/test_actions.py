import pytest
from unittest.mock import patch, MagicMock


def test_speak_calls_say(mocker):
    mock_run = mocker.patch("subprocess.run")
    from actions.tts import speak
    speak("안녕하세요", voice="Yuna", rate=200)
    mock_run.assert_called_once_with(
        ["say", "-v", "Yuna", "-r", "200", "안녕하세요"], check=True
    )


def test_run_applescript(mocker):
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(stdout="result\n", returncode=0)
    from actions.applescript import run_applescript
    result = run_applescript('tell application "Finder" to activate')
    assert result == "result"
    mock_run.assert_called_once()


def test_take_screenshot(mocker, tmp_path):
    mocker.patch("subprocess.run")
    mock_read = mocker.patch("builtins.open", mocker.mock_open(read_data=b"PNG_DATA"))
    mocker.patch("os.unlink")
    from actions.screen import take_screenshot
    data = take_screenshot()
    assert data == b"PNG_DATA"


def test_click_calls_pyautogui(mocker):
    mock_pg = mocker.patch("actions.mouse_keyboard.pyautogui")
    from actions.mouse_keyboard import click
    click(100, 200)
    mock_pg.click.assert_called_once_with(100, 200)


def test_type_text_calls_pyautogui(mocker):
    mock_pg = mocker.patch("actions.mouse_keyboard.pyautogui")
    from actions.mouse_keyboard import type_text
    type_text("hello")
    mock_pg.typewrite.assert_called_once_with("hello", interval=0.05)


def test_press_key_calls_pyautogui(mocker):
    mock_pg = mocker.patch("actions.mouse_keyboard.pyautogui")
    from actions.mouse_keyboard import press_key
    press_key("enter")
    mock_pg.press.assert_called_once_with("enter")


def test_scroll_calls_pyautogui(mocker):
    mock_pg = mocker.patch("actions.mouse_keyboard.pyautogui")
    from actions.mouse_keyboard import scroll
    scroll(100, 200, "down", 3)
    mock_pg.scroll.assert_called_once_with(-3, x=100, y=200)


def test_click_element_by_name_success(mocker):
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0)
    from actions.accessibility import click_element_by_name
    result = click_element_by_name("Safari", "OK")
    assert result is True


def test_click_element_by_name_failure(mocker):
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=1)
    from actions.accessibility import click_element_by_name
    result = click_element_by_name("Safari", "MissingButton")
    assert result is False
