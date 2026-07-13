import pytest
from unittest.mock import patch, MagicMock


def test_speak_calls_say(mocker):
    mock_run = mocker.patch("subprocess.run")
    from actions.tts import speak
    speak("안녕하세요", voice="Yuna", rate=200)
    mock_run.assert_called_once_with(
        ["say", "-v", "Yuna", "-r", "200", "안녕하세요"], check=True
    )


def _nvidia_tts_config(**overrides):
    from config.loader import TTSConfig
    cfg = TTSConfig(
        provider="nvidia",
        nvidia_api_key="nvapi-test",
        nvidia_function_id="func-123",
        nvidia_voice="Chatterbox-Multilingual.ko-KR.Male",
        nvidia_language_code="ko-KR",
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def test_speak_uses_nvidia_when_provider_is_nvidia(mocker):
    mock_run = mocker.patch("subprocess.run")
    mock_speak_nvidia = mocker.patch("actions.tts._speak_nvidia")
    from actions.tts import speak

    cfg = _nvidia_tts_config()
    speak("안녕하세요", tts_config=cfg)

    mock_speak_nvidia.assert_called_once_with("안녕하세요", cfg)
    mock_run.assert_not_called()


def test_speak_nvidia_calls_riva_and_plays_audio(mocker):
    import sys
    riva_module = MagicMock()
    riva_module.client.AudioEncoding.LINEAR_PCM = 1
    sd_module = MagicMock()
    np_module = MagicMock()
    np_module.frombuffer.return_value = "decoded_audio"

    with patch.dict(sys.modules, {
        "riva.client": riva_module.client,
        "riva": riva_module,
        "sounddevice": sd_module,
        "numpy": np_module,
    }):
        mock_future = MagicMock()
        mock_future.result.return_value = MagicMock(audio=b"raw-pcm-bytes")
        riva_module.client.SpeechSynthesisService.return_value.synthesize.return_value = mock_future

        from actions.tts import _speak_nvidia
        cfg = _nvidia_tts_config()
        _speak_nvidia("안녕하세요", cfg)

        riva_module.client.Auth.assert_called_once()
        auth_kwargs = riva_module.client.Auth.call_args.kwargs
        assert auth_kwargs["uri"] == "grpc.nvcf.nvidia.com:443"
        assert ["function-id", "func-123"] in auth_kwargs["metadata_args"]
        assert ["authorization", "Bearer nvapi-test"] in auth_kwargs["metadata_args"]

        synth_kwargs = riva_module.client.SpeechSynthesisService.return_value.synthesize.call_args.kwargs
        assert synth_kwargs["text"] == "안녕하세요"
        assert synth_kwargs["voice_name"] == "Chatterbox-Multilingual.ko-KR.Male"
        assert synth_kwargs["language_code"] == "ko-KR"
        assert synth_kwargs["future"] is True

        # A bounded timeout must be passed to result(); an NVIDIA hang or slow
        # cold-start must not be able to block speak() indefinitely.
        result_kwargs = mock_future.result.call_args.kwargs
        assert 0 < result_kwargs["timeout"] <= 10

        sd_module.play.assert_called_once_with("decoded_audio", 22050)
        sd_module.wait.assert_called_once()


def test_speak_nvidia_times_out_and_falls_back_to_macos(mocker):
    import sys
    riva_module = MagicMock()
    riva_module.client.AudioEncoding.LINEAR_PCM = 1
    sd_module = MagicMock()
    np_module = MagicMock()
    mock_run = mocker.patch("subprocess.run")

    with patch.dict(sys.modules, {
        "riva.client": riva_module.client,
        "riva": riva_module,
        "sounddevice": sd_module,
        "numpy": np_module,
    }):
        mock_future = MagicMock()
        mock_future.result.side_effect = TimeoutError("synthesis timed out")
        riva_module.client.SpeechSynthesisService.return_value.synthesize.return_value = mock_future

        from actions.tts import speak
        cfg = _nvidia_tts_config()
        speak("완료했습니다", voice="Yuna", rate=200, tts_config=cfg)

        mock_run.assert_called_once_with(
            ["say", "-v", "Yuna", "-r", "200", "완료했습니다"], check=True
        )


def test_speak_falls_back_to_macos_when_nvidia_fails(mocker):
    mock_run = mocker.patch("subprocess.run")
    mocker.patch("actions.tts._speak_nvidia", side_effect=RuntimeError("network down"))
    from actions.tts import speak

    cfg = _nvidia_tts_config()
    speak("완료했습니다", voice="Yuna", rate=200, tts_config=cfg)

    mock_run.assert_called_once_with(
        ["say", "-v", "Yuna", "-r", "200", "완료했습니다"], check=True
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


# ---------- AX window-use snapshot ----------

def _fake_tree():
    """dict-based fake AX tree. _patch_ax wires accessors to read these dicts."""
    btn = {"AXRole": "AXButton", "AXTitle": "확인", "center": (100.0, 200.0)}
    field = {
        "AXRole": "AXTextField", "AXTitle": "주소창",
        "AXValue": "mail.google.com", "center": (300.0, 50.0),
    }
    group = {"AXRole": "AXGroup", "AXChildren": [btn, field]}
    window = {"AXRole": "AXWindow", "AXTitle": "테스트 창", "AXChildren": [group]}
    return window, btn, field


def _patch_ax(monkeypatch, window, trusted=True, app_name="TestApp"):
    from actions import accessibility as ax
    ax.clear_target_app()
    monkeypatch.setattr(ax, "_ax_trusted", lambda: trusted)
    monkeypatch.setattr(ax, "_frontmost_app", lambda: (app_name, 123))
    monkeypatch.setattr(ax, "_running_apps", lambda: [(app_name, 123)])
    monkeypatch.setattr(ax, "_ax_app", lambda pid: {"AXWindows": [window]})
    monkeypatch.setattr(ax, "_ax_attr", lambda elem, name: elem.get(name))
    monkeypatch.setattr(ax, "_ax_center", lambda elem: elem.get("center"))
    monkeypatch.setattr(ax, "_ax_actions", lambda elem: elem.get("actions", []))
    monkeypatch.setattr(ax, "_ax_perform",
                        lambda elem, action: elem.get("perform_ok", True))
    monkeypatch.setattr(ax, "_ax_settable",
                        lambda elem, name: elem.get("settable", False))
    monkeypatch.setattr(
        ax, "_ax_set",
        lambda elem, name, v: (elem.setdefault("set_values", []).append(v), True)[1],
    )


def test_snapshot_lists_interactive_elements_numbered(monkeypatch):
    from actions.accessibility import snapshot_screen
    window, _, _ = _fake_tree()
    _patch_ax(monkeypatch, window)
    text = snapshot_screen()
    assert text.startswith('현재 앱: TestApp — 창: "테스트 창"')
    assert '[1] 버튼 "확인"' in text
    assert '[2] 텍스트필드 "주소창" 값="mail.google.com"' in text


def test_snapshot_error_without_ax_trust(monkeypatch):
    from actions.accessibility import snapshot_screen
    window, _, _ = _fake_tree()
    _patch_ax(monkeypatch, window, trusted=False)
    text = snapshot_screen()
    assert text.startswith("error: 접근성 권한")


def test_snapshot_advises_screenshot_fallback_when_few_elements(monkeypatch):
    from actions.accessibility import snapshot_screen
    window, _, _ = _fake_tree()   # only 2 interactive elements (< 5)
    _patch_ax(monkeypatch, window)
    text = snapshot_screen()
    assert "screenshot" in text


def test_snapshot_caps_listed_elements(monkeypatch):
    from actions.accessibility import snapshot_screen
    buttons = [
        {"AXRole": "AXButton", "AXTitle": f"b{i}", "center": (10.0, 10.0)}
        for i in range(200)
    ]
    window = {"AXRole": "AXWindow", "AXTitle": "많음", "AXChildren": buttons}
    _patch_ax(monkeypatch, window)
    text = snapshot_screen()
    assert "[150]" in text
    assert "[151]" not in text


def test_snapshot_skips_elements_without_geometry(monkeypatch):
    from actions.accessibility import snapshot_screen
    ghost = {"AXRole": "AXButton", "AXTitle": "유령"}   # no center -> zero-size
    real = {"AXRole": "AXButton", "AXTitle": "실재", "center": (5.0, 5.0)}
    window = {"AXRole": "AXWindow", "AXChildren": [ghost, real]}
    _patch_ax(monkeypatch, window)
    text = snapshot_screen()
    assert "유령" not in text
    assert '[1] 버튼 "실재"' in text


def test_new_snapshot_invalidates_previous_ids(monkeypatch):
    from actions.accessibility import snapshot_screen, element_known
    window, _, _ = _fake_tree()
    _patch_ax(monkeypatch, window)
    snapshot_screen()
    assert element_known(1) is True
    empty = {"AXRole": "AXWindow", "AXChildren": []}
    _patch_ax(monkeypatch, empty)
    snapshot_screen()
    assert element_known(1) is False


def test_element_center_is_fresh_at_click_time(monkeypatch):
    from actions.accessibility import snapshot_screen, element_center
    window, btn, _ = _fake_tree()
    _patch_ax(monkeypatch, window)
    snapshot_screen()
    btn["center"] = (555.0, 666.0)   # window moved after the snapshot
    assert element_center(1) == (555.0, 666.0)


def test_element_center_none_when_element_gone(monkeypatch):
    from actions.accessibility import snapshot_screen, element_center
    window, btn, _ = _fake_tree()
    _patch_ax(monkeypatch, window)
    snapshot_screen()
    del btn["center"]                # element no longer resolves
    assert element_center(1) is None


# ---------- independent actuation (AXPress / AXSetValue / target pinning) ----------

def test_press_element_uses_ax_action(monkeypatch):
    from actions.accessibility import snapshot_screen, press_element
    window, btn, _ = _fake_tree()
    btn["actions"] = ["AXPress"]
    _patch_ax(monkeypatch, window)
    snapshot_screen()
    assert press_element(1) == "pressed element 1 (AXPress)"


def test_press_element_none_without_ax_action(monkeypatch):
    from actions.accessibility import snapshot_screen, press_element
    window, btn, _ = _fake_tree()
    btn["actions"] = []
    _patch_ax(monkeypatch, window)
    snapshot_screen()
    assert press_element(1) is None


def test_press_element_double_prefers_axopen(monkeypatch):
    from actions.accessibility import snapshot_screen, press_element
    window, btn, _ = _fake_tree()
    btn["actions"] = ["AXPress", "AXOpen"]
    _patch_ax(monkeypatch, window)
    snapshot_screen()
    assert press_element(1, double=True) == "pressed element 1 (AXOpen)"


def test_press_element_none_when_perform_fails(monkeypatch):
    from actions.accessibility import snapshot_screen, press_element
    window, btn, _ = _fake_tree()
    btn["actions"] = ["AXPress"]
    btn["perform_ok"] = False
    _patch_ax(monkeypatch, window)
    snapshot_screen()
    assert press_element(1) is None


def test_set_element_value_success(monkeypatch):
    from actions.accessibility import snapshot_screen, set_element_value
    window, _, field = _fake_tree()
    field["settable"] = True
    _patch_ax(monkeypatch, window)
    snapshot_screen()
    assert set_element_value(2, "hello") == "value set on element 2"
    assert field["set_values"] == ["hello"]


def test_set_element_value_not_settable(monkeypatch):
    from actions.accessibility import snapshot_screen, set_element_value
    window, _, field = _fake_tree()
    _patch_ax(monkeypatch, window)
    snapshot_screen()
    assert set_element_value(2, "hello").startswith("error: 이 요소에는")


def test_snapshot_uses_pinned_target_not_frontmost(monkeypatch):
    from actions import accessibility as ax
    window, _, _ = _fake_tree()
    _patch_ax(monkeypatch, window)
    seen_pids = []
    monkeypatch.setattr(
        ax, "_ax_app", lambda pid: seen_pids.append(pid) or {"AXWindows": [window]}
    )
    assert ax.set_target_app("TestApp") is True
    # user switches to another app — snapshot must ignore the frontmost
    monkeypatch.setattr(ax, "_frontmost_app", lambda: ("OtherApp", 999))
    text = ax.snapshot_screen()
    assert text.startswith("현재 앱: TestApp")
    assert seen_pids == [123]


def test_snapshot_pins_first_app_without_explicit_target(monkeypatch):
    from actions import accessibility as ax
    window, _, _ = _fake_tree()
    _patch_ax(monkeypatch, window)
    ax.snapshot_screen()                      # pins TestApp (123)
    monkeypatch.setattr(ax, "_frontmost_app", lambda: ("OtherApp", 999))
    text = ax.snapshot_screen()
    assert text.startswith("현재 앱: TestApp")


def test_snapshot_errors_when_target_app_gone(monkeypatch):
    from actions import accessibility as ax
    window, _, _ = _fake_tree()
    _patch_ax(monkeypatch, window)
    assert ax.set_target_app("TestApp") is True
    monkeypatch.setattr(ax, "_running_apps", lambda: [])
    text = ax.snapshot_screen()
    assert text.startswith("error: 대상 앱")
