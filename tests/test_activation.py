import pytest
from unittest.mock import patch, MagicMock
from activation.hotkey import HotkeyListener
from activation.wake_word import WakeWordListener


def test_hotkey_listener_calls_callback(mocker):
    triggered = []
    listener = HotkeyListener("alt+space", lambda: triggered.append(True))
    mock_keyboard = mocker.patch("activation.hotkey.keyboard")
    mock_keyboard.add_hotkey.return_value = None
    listener.start()
    mock_keyboard.add_hotkey.assert_called_once()


def test_wake_word_listener_init():
    listener = WakeWordListener("hey desk", lambda: None)
    assert listener._phrase == "hey desk"
