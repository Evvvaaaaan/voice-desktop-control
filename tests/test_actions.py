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


def test_click_glides_then_clicks(mocker):
    mock_pg = mocker.patch("actions.mouse_keyboard.pyautogui")
    from actions.mouse_keyboard import click
    click(100, 200)
    # Cursor visibly moves to the target first (with a duration), then clicks.
    assert mock_pg.moveTo.call_args.args == (100, 200)
    assert mock_pg.moveTo.call_args.kwargs["duration"] > 0
    mock_pg.click.assert_called_once_with()


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


# ---------------------------------------------------------------------------
# TTS must never raise (missing voice / broken `say`)
# ---------------------------------------------------------------------------

def test_speak_survives_say_failure(mocker):
    import subprocess as sp
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "-v" in cmd:
            raise sp.CalledProcessError(1, cmd)
        return MagicMock()

    mocker.patch("subprocess.run", side_effect=fake_run)
    from actions.tts import speak
    speak("안녕하세요", voice="NoSuchVoice", rate=200)   # must not raise
    assert ["say", "-r", "200", "안녕하세요"] in calls    # voiceless fallback


def test_speak_survives_total_say_failure(mocker):
    mocker.patch("subprocess.run", side_effect=OSError("say missing"))
    from actions.tts import speak
    speak("안녕하세요")                                    # must not raise


# ---------------------------------------------------------------------------
# Keyboard: Korean text and key combos
# ---------------------------------------------------------------------------

def test_type_text_korean_goes_through_clipboard(mocker):
    mock_sub = mocker.patch("actions.mouse_keyboard.subprocess.run")
    import actions.mouse_keyboard as mk
    mock_typewrite = mocker.patch.object(mk.pyautogui, "typewrite")
    mock_hotkey = mocker.patch.object(mk.pyautogui, "hotkey")

    mk.type_text("안녕하세요")

    mock_typewrite.assert_not_called()
    mock_sub.assert_called_once()
    assert mock_sub.call_args.args[0] == ["pbcopy"]
    assert mock_sub.call_args.kwargs["input"] == "안녕하세요".encode("utf-8")
    mock_hotkey.assert_called_once_with("command", "v")


def test_type_text_ascii_uses_typewrite(mocker):
    import actions.mouse_keyboard as mk
    mock_typewrite = mocker.patch.object(mk.pyautogui, "typewrite")
    mock_hotkey = mocker.patch.object(mk.pyautogui, "hotkey")
    mk.type_text("hello")
    mock_typewrite.assert_called_once()
    mock_hotkey.assert_not_called()


def test_press_key_combo_uses_hotkey(mocker):
    import actions.mouse_keyboard as mk
    mock_hotkey = mocker.patch.object(mk.pyautogui, "hotkey")
    mock_press = mocker.patch.object(mk.pyautogui, "press")
    mk.press_key("cmd+t")
    mock_hotkey.assert_called_once_with("command", "t")
    mock_press.assert_not_called()


def test_press_key_single_uses_press(mocker):
    import actions.mouse_keyboard as mk
    mock_hotkey = mocker.patch.object(mk.pyautogui, "hotkey")
    mock_press = mocker.patch.object(mk.pyautogui, "press")
    mk.press_key("enter")
    mock_press.assert_called_once_with("enter")
    mock_hotkey.assert_not_called()


# ---------------------------------------------------------------------------
# Screenshot downscale for vision payloads
# ---------------------------------------------------------------------------

def test_take_screenshot_captures_active_display_and_downscales(mocker):
    mock_run = mocker.patch("actions.screen.subprocess.run",
                            return_value=MagicMock(returncode=0))
    mocker.patch("actions.screen.os.path.getsize", return_value=1000)
    mocker.patch("actions.screen.active_screen_rect",
                 return_value=(-1920.0, 0.0, 1920.0, 1080.0))
    from actions.screen import take_screenshot
    take_screenshot()
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert cmds[0][0] == "screencapture"
    assert "-R" in cmds[0]
    region = cmds[0][cmds[0].index("-R") + 1]
    assert region.startswith("-1920")       # external display region, not main
    assert cmds[1][0] == "sips"


def test_last_capture_rect_matches_active_display_on_success(mocker):
    """After a successful region capture, click dispatch must map against
    the SAME rect that was actually captured/shown, not a freshly re-resolved
    active_screen_rect() — see agent/tools.py's _to_logical."""
    mocker.patch("actions.screen.subprocess.run",
                 return_value=MagicMock(returncode=0))
    mocker.patch("actions.screen.os.path.getsize", return_value=1000)
    mocker.patch("actions.screen.active_screen_rect",
                 return_value=(-1920.0, 0.0, 1920.0, 1080.0))
    import actions.screen as screen
    screen._capture_active_display_png("/tmp/x.png")
    assert screen.last_capture_rect() == (-1920.0, 0.0, 1920.0, 1080.0)


def test_last_capture_rect_falls_back_to_main_display_when_region_capture_fails(mocker):
    """A region capture can fail outright (observed with a negative-origin
    region for an external monitor) — screencapture then silently falls back
    to capturing the MAIN display instead. last_capture_rect() must reflect
    what was ACTUALLY captured, not the external-monitor rect that was
    requested, or clicks get mapped onto the wrong display's coordinates."""
    mocker.patch("actions.screen.subprocess.run",
                 return_value=MagicMock(returncode=1))   # region capture fails
    mocker.patch("actions.screen.active_screen_rect",
                 return_value=(-1920.0, 0.0, 1920.0, 1080.0))
    mocker.patch("actions.screen._main_display_rect",
                 return_value=(0.0, 0.0, 2560.0, 1440.0))
    import actions.screen as screen
    screen._capture_active_display_png("/tmp/x.png")
    assert screen.last_capture_rect() == (0.0, 0.0, 2560.0, 1440.0)


def test_move_mouse_glides(mocker):
    mock_pg = mocker.patch("actions.mouse_keyboard.pyautogui")
    from actions.mouse_keyboard import move_mouse
    move_mouse(300, 400)
    assert mock_pg.moveTo.call_args.args == (300, 400)
    assert mock_pg.moveTo.call_args.kwargs["duration"] > 0
    mock_pg.click.assert_not_called()


def test_double_click_glides_then_double_clicks(mocker):
    mock_pg = mocker.patch("actions.mouse_keyboard.pyautogui")
    from actions.mouse_keyboard import double_click
    double_click(50, 60)
    assert mock_pg.moveTo.call_args.args == (50, 60)
    mock_pg.doubleClick.assert_called_once_with()


def test_scroll_without_position_stays_put(mocker):
    """scroll(0, 0, ...) must NOT jump the pointer to the corner (failsafe)."""
    mock_pg = mocker.patch("actions.mouse_keyboard.pyautogui")
    from actions.mouse_keyboard import scroll
    scroll(0, 0, "down", 3)
    mock_pg.scroll.assert_called_once_with(-3)      # no x/y → current position


# ---------------------------------------------------------------------------
# Grid-overlay screenshot (computer-use click accuracy)
# ---------------------------------------------------------------------------

def test_take_screenshot_with_grid_burns_in_gridlines_and_labels(mocker, tmp_path):
    """The overlay must actually change pixels (gridlines) — a no-op overlay
    would silently regress click accuracy back to unmarked guessing."""
    from PIL import Image
    import actions.screen as screen_mod

    # A flat white 400x300 "screenshot" so any drawn line is trivially detectable.
    src = tmp_path / "shot.png"
    Image.new("RGB", (400, 300), (255, 255, 255)).save(src)

    def fake_capture(tmp_path_arg, with_cursor=False):
        Image.open(src).save(tmp_path_arg)

    mocker.patch.object(screen_mod, "_capture_active_display_png", fake_capture)
    result = screen_mod.take_screenshot_with_grid()

    out = Image.open(screen_mod.io.BytesIO(result))
    assert out.format == "PNG"
    pixels = out.load()
    # Somewhere along the vertical gridline near x≈40% (400*0.4=160) there
    # must be a non-white pixel — proof a line was actually drawn.
    col_has_line = any(pixels[160, y] != (255, 255, 255) for y in range(0, 300, 5))
    assert col_has_line


def test_take_screenshot_with_grid_passes_cursor_flag(mocker):
    """with_cursor must reach _capture_active_display_png unchanged — it's
    what lets the move-then-verify-then-click pattern see the real pointer."""
    from actions.screen import take_screenshot_with_grid
    from PIL import Image

    mock_capture = mocker.patch("actions.screen._capture_active_display_png")

    def fake_capture(tmp_path_arg, with_cursor=False):
        Image.new("RGB", (100, 100), "white").save(tmp_path_arg)
        fake_capture.seen = with_cursor
    mock_capture.side_effect = fake_capture

    take_screenshot_with_grid(with_cursor=True)
    assert fake_capture.seen is True
    take_screenshot_with_grid(with_cursor=False)
    assert fake_capture.seen is False


def test_capture_with_cursor_passes_dash_c_flag(mocker):
    mock_run = mocker.patch("actions.screen.subprocess.run",
                            return_value=MagicMock(returncode=0))
    mocker.patch("actions.screen.os.path.getsize", return_value=1000)
    mocker.patch("actions.screen.active_screen_rect",
                 return_value=(0.0, 0.0, 1000.0, 800.0))
    from actions.screen import _capture_active_display_png
    _capture_active_display_png("/tmp/x.png", with_cursor=True)
    flags = mock_run.call_args.args[0]
    assert "-C" in flags
    mock_run.reset_mock()
    _capture_active_display_png("/tmp/x.png", with_cursor=False)
    flags = mock_run.call_args.args[0]
    assert "-C" not in flags


def test_click_waits_for_ui_to_settle(mocker):
    import actions.mouse_keyboard as mk
    mocker.patch.object(mk.pyautogui, "moveTo")
    mocker.patch.object(mk.pyautogui, "click")
    mock_sleep = mocker.patch.object(mk.time, "sleep")
    mk.click(100, 100)
    mock_sleep.assert_called_once()
    assert mock_sleep.call_args.args[0] > 0


def test_double_click_waits_for_ui_to_settle(mocker):
    import actions.mouse_keyboard as mk
    mocker.patch.object(mk.pyautogui, "moveTo")
    mocker.patch.object(mk.pyautogui, "doubleClick")
    mock_sleep = mocker.patch.object(mk.time, "sleep")
    mk.double_click(100, 100)
    mock_sleep.assert_called_once()
