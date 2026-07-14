import types

import pytest
from ui.notch_hud import (
    NotchHUD,
    _label,
    _format_provider_summary,
    _format_provider_columns,
    _bar_heights,
    _frame_for,
    _SIZES,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_label_known_and_unknown():
    assert _label("macos") == "로컬"
    assert _label("claude") == "Claude"
    assert _label("nvidia") == "NVIDIA"
    assert _label("brandnew") == "Brandnew"   # graceful fallback
    assert _label("") == "—"


def test_provider_summary_format():
    s = _format_provider_summary("macos", "claude", "claude-sonnet-4-6", "nvidia", "x")
    assert s == "STT 로컬 · LLM Claude · TTS NVIDIA"


def test_provider_columns_structure():
    cols = _format_provider_columns(
        "macos", "claude", "claude-sonnet-4-6", "nvidia",
        "Chatterbox-Multilingual.ko-KR.Male",
    )
    assert [c["title"] for c in cols] == ["STT", "LLM", "TTS"]
    assert cols[0]["lines"] == ["로컬"]
    assert cols[1]["lines"] == ["Claude", "claude-sonnet-4-6"]
    assert cols[2]["lines"][0] == "NVIDIA"
    assert cols[2]["lines"][1] == "Chatterbox"   # voice compacted


def test_bar_heights_count_and_range():
    hs = _bar_heights(0.5, 6)
    assert len(hs) == 6
    assert all(0.08 <= h <= 1.0 for h in hs)


def test_bar_heights_scales_with_level():
    assert sum(_bar_heights(0.9)) > sum(_bar_heights(0.1))


def test_bar_heights_clamps_out_of_range_input():
    assert all(0.08 <= h <= 1.0 for h in _bar_heights(-5.0))
    assert all(0.08 <= h <= 1.0 for h in _bar_heights(5.0))


def test_bar_heights_custom_count():
    assert len(_bar_heights(0.5, 3)) == 3


def test_frame_for_is_top_centered():
    x, y, w, h = _frame_for((400, 120), 1440, 900)
    assert (w, h) == (400, 120)
    assert x == (1440 - 400) / 2       # horizontally centered
    assert y == 900 - 120              # top edge flush with screen top


# ---------------------------------------------------------------------------
# Interaction state machine (rendering stubbed so no AppKit is exercised)
# ---------------------------------------------------------------------------

def _isolated_hud():
    hud = NotchHUD()
    hud._initialized = True
    hud._ensure_init = lambda: None
    hud._render = lambda: None
    hud._render_bars = lambda: None
    hud._schedule_hover_expand = lambda: None
    return hud


def test_visual_idle_substates():
    hud = _isolated_hud()
    assert hud._visual() == "idle_collapsed"
    hud._hovering = True
    assert hud._visual() == "idle_peek"
    hud._pinned = True
    assert hud._visual() == "idle_pinned"   # pinned wins over hover


def test_visual_non_idle_and_fallback():
    hud = _isolated_hud()
    hud._state = "listening"
    assert hud._visual() == "listening"
    hud._state = "totally_unknown"
    assert hud._visual() == "processing"    # safe fallback


def test_all_visuals_have_sizes():
    for key in ("idle_collapsed", "idle_peek", "idle_pinned", "listening",
                "processing", "executing", "success", "error", "danger_confirm"):
        assert key in _SIZES


def test_hover_dwell_expands_only_after_fire():
    hud = _isolated_hud()
    hud._hover_enter()
    assert hud._hover_inside is True
    assert hud._hovering is False           # dwell pending, not expanded yet
    hud._hover_expand_fire()
    assert hud._hovering is True


def test_hover_exit_before_dwell_cancels_expansion():
    hud = _isolated_hud()
    hud._hover_enter()
    hud._hover_exit()
    hud._hover_expand_fire()                # timer fires late, pointer already gone
    assert hud._hovering is False


def test_hover_confirm_expands_immediately_without_dwell():
    """A post-animation reconcile (cursor proven present) must expand at once,
    not arm another dwell — this is what keeps a re-hover after a collapse
    from feeling laggy."""
    hud = _isolated_hud()
    hud._hover_confirm()
    assert hud._hover_inside is True
    assert hud._hovering is True            # expanded now, no _hover_expand_fire needed


def test_duplicate_hover_confirm_does_not_render_again():
    """Animation completion can reconcile hover after Swift suppressed frame
    resize artifacts. If the hover state is already current, rendering again
    feeds a needless Python↔Swift loop during open/close."""
    hud = _isolated_hud()
    render_calls = []
    hud._render = lambda: render_calls.append(1)
    hud._hover_confirm()
    hud._hover_confirm()
    assert render_calls == [1]


def test_duplicate_hover_exit_does_not_render_again():
    hud = _isolated_hud()
    render_calls = []
    hud._render = lambda: render_calls.append(1)
    hud._hover_exit()
    assert render_calls == []


def test_hover_confirm_ignored_when_not_idle():
    hud = _isolated_hud()
    hud._state = "listening"
    hud._hover_confirm()
    assert hud._hovering is False           # active-state UI wins, no peek expansion


def test_hover_confirm_while_pinned_does_not_rerender_same_visual():
    hud = _isolated_hud()
    hud._pinned = True
    render_calls = []
    hud._render = lambda: render_calls.append(1)
    hud._hover_confirm()
    assert hud._hover_inside is True
    assert hud._hovering is True
    assert render_calls == []               # still idle_pinned, no Swift churn


def test_hover_exit_while_pinned_does_not_rerender_same_visual():
    hud = _isolated_hud()
    hud._pinned = True
    hud._hover_inside = True
    hud._hovering = True
    render_calls = []
    hud._render = lambda: render_calls.append(1)
    hud._hover_exit()
    assert hud._hover_inside is False
    assert hud._hovering is False
    assert render_calls == []               # still idle_pinned


def test_click_toggles_pin_when_idle():
    hud = _isolated_hud()
    hud._toggle_pin()
    assert hud._pinned is True
    hud._toggle_pin()
    assert hud._pinned is False


def test_click_ignored_when_not_idle():
    hud = _isolated_hud()
    hud._state = "processing"
    hud._toggle_pin()
    assert hud._pinned is False


def test_set_state_non_idle_resets_expansion():
    hud = _isolated_hud()
    hud._pinned = True
    hud._hovering = True
    hud._hover_inside = True
    hud.set_state("listening")
    assert hud._state == "listening"
    assert hud._pinned is False
    assert hud._hovering is False
    assert hud._hover_inside is False


def test_set_provider_info_and_mic_level_store():
    hud = _isolated_hud()
    hud.set_provider_info("macos", "ollama", "llama3", "macos", "Yuna")
    assert hud._provider == ("macos", "ollama", "llama3", "macos", "Yuna")
    hud.update_mic_level(0.7)
    assert hud._mic_level == 0.7


def test_update_metrics_contract_preserved():
    hud = _isolated_hud()
    hud.update_metrics({"success": 0.94})
    assert hud._metrics == {"success": 0.94}


# ---------------------------------------------------------------------------
# Physical-notch sizing + transcript display
# ---------------------------------------------------------------------------

from ui.notch_hud import _visual_size, _truncate


def test_visual_size_without_notch_is_passthrough():
    w, h = _SIZES["processing"]
    assert _visual_size("processing") == (w, h, h)
    cw, ch = _SIZES["idle_collapsed"]
    assert _visual_size("idle_collapsed") == (cw, ch, ch)


def test_visual_size_ignores_notch_inset_for_expanded_visuals():
    w, h = _SIZES["listening"]
    total_w, total_h, content_h = _visual_size(
        "listening", top_inset=32.0, notch_size=(185.0, 32.0)
    )
    assert total_w == w
    assert total_h == h            # no transparent top band in expanded states
    assert content_h == h


def test_visual_size_collapsed_wraps_physical_notch_with_lip():
    # NotchNook look: a bit wider than the notch, small lip below the menu bar.
    from ui.notch_hud import _COLLAPSED_EXTRA_W, _COLLAPSED_LIP
    w, th, ch = _visual_size(
        "idle_collapsed", top_inset=32.0, notch_size=(185.0, 32.0)
    )
    assert w == 185.0 + _COLLAPSED_EXTRA_W
    assert th == ch == 32.0 + _COLLAPSED_LIP


def test_truncate():
    assert _truncate("short") == "short"
    long = "가" * 60
    out = _truncate(long, 44)
    assert len(out) == 44 and out.endswith("…")


def test_set_transcript_stores_stripped_text():
    hud = _isolated_hud()
    hud.set_transcript("  크롬 열어줘  ")
    assert hud._transcript == "크롬 열어줘"
    hud.set_transcript("")
    assert hud._transcript == ""


# ---------------------------------------------------------------------------
# Danger-confirm buttons
# ---------------------------------------------------------------------------

class _FakeDecision:
    def __init__(self):
        self.value = None

    def resolve(self, allow):
        if self.value is None:
            self.value = allow


def test_danger_resolve_routes_to_armed_decision():
    hud = _isolated_hud()
    d = _FakeDecision()
    hud.arm_danger_prompt(d)
    hud._danger_resolve(True)
    assert d.value is True
    assert hud._danger_decision is None      # one-shot


def test_danger_resolve_without_armed_decision_is_noop():
    hud = _isolated_hud()
    hud._danger_resolve(True)                # must not raise


def test_click_at_routes_danger_buttons_and_falls_back_to_pin():
    hud = _isolated_hud()
    d = _FakeDecision()
    hud.arm_danger_prompt(d)
    hud._danger_hit_zones = [((110, 10, 100, 28), True), ((226, 10, 100, 28), False)]
    hud._click_at(160, 24)                    # inside 실행
    assert d.value is True
    # outside any zone → pin toggle (idle only; here state is idle)
    hud._danger_hit_zones = []
    hud._click_at(5, 5)
    assert hud._pinned is True


# ---------------------------------------------------------------------------
# NotchNook-style widgets (clock / now playing)
# ---------------------------------------------------------------------------

from ui.notch_hud import _format_clock, _media_line, _pinned_size, _PINNED_WITH_WIDGETS


def test_format_clock_korean():
    from datetime import datetime
    time_s, date_s = _format_clock(datetime(2026, 7, 2, 16, 5))   # Thursday
    assert time_s == "16:05"
    assert date_s == "7월 2일 목요일"


def test_media_line_with_and_without_track():
    assert _media_line(("멍멍이", "노라조")) == ("멍멍이", "노라조")
    title, artist = _media_line(None)
    assert title == "재생 중인 음악 없음" and artist == ""
    long_title = "가" * 40
    assert _media_line((long_title, ""))[0].endswith("…")


def test_pinned_size_grows_only_with_widgets():
    assert _pinned_size(True, True) == _PINNED_WITH_WIDGETS
    assert _pinned_size(True, False) == _PINNED_WITH_WIDGETS
    assert _pinned_size(False, False) == _SIZES["idle_pinned"]


def test_pinned_size_adds_height_only_when_routines_present():
    """The saved-routines row is optional, so its height is added only when
    there are routines — otherwise the panel would carry a dead gap above the
    bottom command palette."""
    from ui.notch_hud import _PINNED_ROUTINES_EXTRA
    base_w, base_h = _pinned_size(True, True, has_routines=False)
    assert (base_w, base_h) == _PINNED_WITH_WIDGETS
    with_w, with_h = _pinned_size(True, True, has_routines=True)
    assert with_w == base_w
    assert with_h == base_h + _PINNED_ROUTINES_EXTRA


def test_set_widgets_stores_flags():
    hud = _isolated_hud()
    hud.set_widgets(False, True)
    assert hud._show_clock is False and hud._show_media is True
    # New options default true and are individually settable.
    assert hud._show_battery is True
    assert hud._hover_to_expand is True
    assert hud._interaction_sounds is True


def test_set_widgets_stores_new_options():
    hud = _isolated_hud()
    hud.set_widgets(True, True, show_battery=False, hover_to_expand=False,
                    interaction_sounds=False)
    assert hud._show_battery is False
    assert hud._hover_to_expand is False
    assert hud._interaction_sounds is False


def test_hover_to_expand_false_disables_dwell_schedule():
    """When the user turns off auto-expand-on-hover, entering the pill must
    not arm the dwell timer at all — only a click should ever expand it."""
    hud = NotchHUD()
    hud._initialized = True
    hud._ensure_init = lambda: None
    hud._render = lambda: None
    hud.set_widgets(True, True, hover_to_expand=False)
    hud._hover_enter()
    assert hud._hover_inside is True
    assert hud._hover_timer is None   # no dwell timer armed
    hud._toggle_pin()                 # click still works
    assert hud._pinned is True


def test_render_payload_omits_battery_when_disabled():
    hud = _isolated_hud()
    hud.set_widgets(True, True, show_battery=False)
    hud._pinned = True
    hud._state = "idle"
    payload = hud._render_payload()
    assert payload["battery"] == ""
    assert payload["batteryPercent"] is None


def test_render_payload_carries_structured_battery_fields(mocker):
    mocker.patch("ui.notch_hud._battery_status", return_value=(42, True))
    hud = _isolated_hud()
    hud.set_widgets(True, True, show_battery=True)
    hud._pinned = True
    hud._state = "idle"
    payload = hud._render_payload()
    assert payload["batteryPercent"] == 42
    assert payload["batteryCharging"] is True
    assert payload["battery"] == "⚡ 42%"


def test_set_open_settings_callback_scheduled_on_main_loop(mocker):
    hud = _isolated_hud()
    calls = []
    callback = lambda: calls.append(1)
    call_after = mocker.Mock()
    app_helper = types.SimpleNamespace(callAfter=call_after)
    mocker.patch.dict(
        "sys.modules",
        {
            "PyObjCTools": types.SimpleNamespace(AppHelper=app_helper),
            "PyObjCTools.AppHelper": app_helper,
        },
    )

    hud.set_open_settings_callback(callback)
    hud._on_swift_event({"event": "openSettings"})

    call_after.assert_called_once_with(callback)
    assert calls == []


def test_open_settings_event_survives_missing_callback():
    hud = _isolated_hud()
    hud._on_swift_event({"event": "openSettings"})   # must not raise


def test_render_payload_carries_interaction_sounds_flag():
    hud = _isolated_hud()
    hud.set_widgets(True, True, interaction_sounds=False)
    payload = hud._render_payload()
    assert payload["interactionSounds"] is False


def test_render_skips_identical_payloads_and_hide_resets_cache():
    class Bridge:
        def __init__(self):
            self.sent = []

        def send(self, payload):
            self.sent.append(payload)
            return True

    hud = NotchHUD()
    hud._initialized = True
    hud._bridge = Bridge()
    hud._visible = True

    hud._render()
    hud._render()
    assert len(hud._bridge.sent) == 1

    hud.hide()
    hud._visible = True
    hud._render()
    assert len(hud._bridge.sent) == 3       # hide command + fresh render


# ---------------------------------------------------------------------------
# Notch text input (long-text confirmation)
# ---------------------------------------------------------------------------

from ui.notch_hud import TextInputRequest, _battery_info, _battery_status


def test_text_input_request_resolve_and_timeout():
    r = TextInputRequest()
    r.resolve("hello")
    r.resolve("late")                      # first resolution wins
    assert r.wait(0.01) == "hello"
    assert TextInputRequest().wait(0.01) is None   # timeout → None


def _wait_until_text_request_ready(hud, timeout=1.0):
    import time
    deadline = time.monotonic() + timeout
    while hud._text_request is None and time.monotonic() < deadline:
        time.sleep(0.005)


def test_request_text_input_returns_submitted_text():
    import threading
    hud = _isolated_hud()
    hud.set_state = lambda s: setattr(hud, "_state", s)

    def submit():
        _wait_until_text_request_ready(hud)
        hud._on_swift_event({"event": "textSubmit", "text": "고친 내용"})

    threading.Thread(target=submit, daemon=True).start()
    hud._state = "executing"
    value = hud.request_text_input("확인해 주세요", "원래 내용", timeout=2.0)
    assert value == "고친 내용"
    assert hud._state == "executing"       # state restored after input
    assert hud._text_request is None


def test_request_text_input_cancel_returns_none():
    import threading
    hud = _isolated_hud()
    hud.set_state = lambda s: setattr(hud, "_state", s)

    def cancel():
        _wait_until_text_request_ready(hud)
        hud._on_swift_event({"event": "textCancel"})

    threading.Thread(target=cancel, daemon=True).start()
    hud._state = "executing"
    assert hud.request_text_input("확인", "draft", timeout=2.0) is None


def test_text_input_visual_has_size():
    assert "text_input" in _SIZES


# ---------------------------------------------------------------------------
# Widget auto-refresh tick chain (regression: _arm_widget_tick was defined
# but never called from anywhere, so the clock/media never updated without
# closing and reopening the panel)
# ---------------------------------------------------------------------------

def test_render_payload_arms_tick_when_pinned(mocker):
    hud = _isolated_hud()
    mock_arm = mocker.patch.object(hud, "_arm_widget_tick")
    hud._pinned = True
    hud._state = "idle"
    hud._render_payload()
    mock_arm.assert_called_once()


def test_render_payload_does_not_arm_tick_when_collapsed(mocker):
    hud = _isolated_hud()
    mock_arm = mocker.patch.object(hud, "_arm_widget_tick")
    hud._pinned = False
    hud._state = "idle"
    hud._render_payload()
    mock_arm.assert_not_called()


def test_arm_widget_tick_starts_a_real_timer():
    hud = _isolated_hud()
    hud._pinned = True
    hud._state = "idle"
    assert hud._tick_timer is None
    hud._arm_widget_tick()
    assert hud._tick_armed is True
    assert hud._tick_timer is not None
    hud._tick_timer.cancel()   # don't let the real 5s timer fire during tests


def test_arm_widget_tick_is_idempotent_while_armed():
    """A second render while a tick is already pending must not stack timers."""
    hud = _isolated_hud()
    hud._pinned = True
    hud._state = "idle"
    hud._arm_widget_tick()
    first_timer = hud._tick_timer
    hud._arm_widget_tick()
    assert hud._tick_timer is first_timer
    first_timer.cancel()


def test_widget_tick_refreshes_media_and_rerenders_while_pinned(mocker):
    hud = _isolated_hud()
    hud._pinned = True
    hud._state = "idle"
    mock_fetch = mocker.patch.object(hud, "_fetch_media_async")
    render_calls = []
    hud._render = lambda: render_calls.append(1)
    hud._widget_tick()
    assert hud._tick_armed is False
    mock_fetch.assert_called_once()
    assert render_calls == [1]


def test_widget_tick_stops_reraming_once_panel_closes():
    """The tick must NOT keep firing after the panel is closed — closing sets
    _pinned False, so _widget_tick's guard should skip refresh+re-render,
    and nothing re-arms the chain."""
    hud = _isolated_hud()
    hud._pinned = False
    hud._state = "idle"
    render_calls = []
    hud._render = lambda: render_calls.append(1)
    hud._widget_tick()
    assert render_calls == []
    assert hud._tick_armed is False


def test_widget_tick_reachms_via_real_render_payload_chain():
    """End-to-end (minus the actual 5s wait): _widget_tick -> _render ->
    _render_payload -> _arm_widget_tick re-arms a fresh timer, proving the
    refresh chain sustains itself for as long as the panel stays pinned."""
    hud = _isolated_hud()
    hud._pinned = True
    hud._state = "idle"
    hud._render = lambda: hud._render_payload()   # exercise the real payload builder
    hud._fetch_media_async = lambda: None

    hud._widget_tick()

    assert hud._tick_armed is True   # re-armed by the render_payload call above
    hud._tick_timer.cancel()


# ---------------------------------------------------------------------------
# Album artwork (thumbnail fetch, caching on track change, payload wiring)
# ---------------------------------------------------------------------------

def _fake_appkit_with_running(mocker, bundle_id_present):
    import types
    fake_appkit = types.ModuleType("AppKit")
    fake_appkit.NSRunningApplication = mocker.Mock()
    fake_appkit.NSRunningApplication.runningApplicationsWithBundleIdentifier_.side_effect = (
        lambda bid: [object()] if bid == bundle_id_present else []
    )
    return fake_appkit


def test_now_playing_returns_app_name_for_control_routing(mocker):
    """The third element (app name) is what lets prev/next buttons know
    which app to send AppleScript control commands to."""
    import sys
    from ui.notch_hud import _now_playing

    mocker.patch.dict(sys.modules, {"AppKit": _fake_appkit_with_running(mocker, "com.apple.Music")})
    mocker.patch(
        "ui.notch_hud.subprocess.run",
        return_value=mocker.Mock(returncode=0, stdout="Song|||Artist|||playing|||30.5|||210.0\n"),
    )
    result = _now_playing()
    assert result == ("Song", "Artist", "Music", True, 30.5, 210.0)


def test_now_playing_includes_paused_tracks_not_just_playing(mocker):
    """Regression: pausing must not make _now_playing (and therefore the
    media card + its resume button) disappear."""
    import sys
    from ui.notch_hud import _now_playing

    mocker.patch.dict(sys.modules, {"AppKit": _fake_appkit_with_running(mocker, "com.apple.Music")})
    mocker.patch(
        "ui.notch_hud.subprocess.run",
        return_value=mocker.Mock(returncode=0, stdout="Song|||Artist|||paused|||0.0|||210.0\n"),
    )
    result = _now_playing()
    assert result == ("Song", "Artist", "Music", False, 0.0, 210.0)


def test_now_playing_converts_spotify_duration_from_milliseconds(mocker):
    """Spotify reports `duration of current track` in milliseconds while Music
    uses seconds — the slider needs both normalized to seconds."""
    import sys
    from ui.notch_hud import _now_playing

    mocker.patch.dict(sys.modules, {"AppKit": _fake_appkit_with_running(mocker, "com.spotify.client")})
    mocker.patch(
        "ui.notch_hud.subprocess.run",
        return_value=mocker.Mock(returncode=0, stdout="Song|||Artist|||playing|||42.0|||210000\n"),
    )
    result = _now_playing()
    assert result == ("Song", "Artist", "Spotify", True, 42.0, 210.0)


def test_fetch_media_async_only_refetches_artwork_on_track_change(mocker):
    """Artwork extraction is the expensive part of a refresh — must not
    happen on every tick, only when the track actually changed."""
    hud = _isolated_hud()
    hud._show_media = True
    hud._media = ("Old Song", "Old Artist", "Music", True)
    hud._media_artwork = "old_art_b64"

    mocker.patch("ui.notch_hud._now_playing", return_value=("Old Song", "Old Artist", "Music", True))
    mock_fetch_art = mocker.patch("ui.notch_hud._fetch_artwork")

    hud._fetch_media_async()
    import time
    time.sleep(0.05)   # the fetch runs on a background thread

    mock_fetch_art.assert_not_called()
    assert hud._media_artwork == "old_art_b64"   # unchanged


def test_fetch_media_async_refetches_artwork_when_track_changes(mocker):
    hud = _isolated_hud()
    hud._show_media = True
    hud._media = ("Old Song", "Old Artist", "Music", True)
    hud._media_artwork = "old_art_b64"

    mocker.patch("ui.notch_hud._now_playing", return_value=("New Song", "New Artist", "Spotify", True))
    mocker.patch("ui.notch_hud._fetch_artwork", return_value="new_art_b64")

    hud._fetch_media_async()
    import time
    time.sleep(0.05)

    assert hud._media_artwork == "new_art_b64"
    assert hud._media == ("New Song", "New Artist", "Spotify", True)


def test_fetch_media_async_clears_artwork_when_nothing_playing(mocker):
    hud = _isolated_hud()
    hud._show_media = True
    hud._media = ("Old Song", "Old Artist", "Music", True)
    hud._media_artwork = "old_art_b64"
    mocker.patch("ui.notch_hud._now_playing", return_value=None)
    mock_fetch_art = mocker.patch("ui.notch_hud._fetch_artwork")

    hud._fetch_media_async()
    import time
    time.sleep(0.05)

    mock_fetch_art.assert_not_called()
    assert hud._media_artwork is None


def test_render_payload_includes_artwork_and_player_app():
    hud = _isolated_hud()
    hud._media = ("Song", "Artist", "Spotify", True, 30.5, 210.0)
    hud._media_artwork = "fake_base64_png"
    hud._pinned = True
    hud._state = "idle"
    payload = hud._render_payload()
    assert payload["mediaArtwork"] == "fake_base64_png"
    assert payload["mediaPlayerApp"] == "Spotify"
    assert payload["mediaPosition"] == 30.5
    assert payload["mediaDuration"] == 210.0


def test_render_payload_empty_artwork_and_app_when_nothing_playing():
    hud = _isolated_hud()
    hud._media = None
    hud._media_artwork = None
    hud._pinned = True
    hud._state = "idle"
    payload = hud._render_payload()
    assert payload["mediaArtwork"] == ""
    assert payload["mediaPlayerApp"] == ""


def test_pinned_panel_widened_for_media_controls_layout():
    # Regression guard: the wider layout must stay wide enough to fit an
    # album art thumbnail + 3 transport buttons alongside the track text.
    assert _PINNED_WITH_WIDGETS[0] >= 700


# ---------------------------------------------------------------------------
# Saved routines exposed for one-click launch in the pinned panel
# ---------------------------------------------------------------------------

def test_render_payload_includes_saved_routine_names(mocker, tmp_path):
    routines_file = tmp_path / "routines.json"
    routines_file.write_text(
        '[{"name": "출근 준비", "steps": []}, {"name": "퇴근 정리", "steps": []}]',
        encoding="utf-8",
    )
    mocker.patch.dict("os.environ", {"VOICEDESK_ROUTINES": str(routines_file)})
    hud = _isolated_hud()
    hud._pinned = True
    hud._state = "idle"
    payload = hud._render_payload()
    assert payload["routines"] == ["출근 준비", "퇴근 정리"]


def test_render_payload_routines_empty_when_no_routines_file(mocker, tmp_path):
    mocker.patch.dict("os.environ", {"VOICEDESK_ROUTINES": str(tmp_path / "missing.json")})
    hud = _isolated_hud()
    hud._pinned = True
    hud._state = "idle"
    payload = hud._render_payload()
    assert payload["routines"] == []


def test_render_payload_routines_empty_when_collapsed(mocker, tmp_path):
    """Routine list is only computed for the pinned panel, not every visual —
    reading the routines file on every collapsed/listening/etc. render would
    be pointless I/O for a visual that never shows it."""
    routines_file = tmp_path / "routines.json"
    routines_file.write_text('[{"name": "테스트", "steps": []}]', encoding="utf-8")
    mocker.patch.dict("os.environ", {"VOICEDESK_ROUTINES": str(routines_file)})
    hud = _isolated_hud()
    hud._pinned = False
    hud._state = "idle"
    payload = hud._render_payload()
    assert payload["routines"] == []


# ---------------------------------------------------------------------------
# Command palette — most-used commands surfaced for one-tap re-run
# ---------------------------------------------------------------------------

from ui.notch_hud import _load_command_suggestions, _FALLBACK_SUGGESTIONS


def _seed_metrics_db(path, rows):
    """rows: list of (command, success). Builds the events table via the real
    collector so the schema stays in sync with production."""
    from metrics.collector import MetricsCollector
    collector = MetricsCollector(str(path))
    for command, success in rows:
        collector.record(command, 0.95, bool(success), 0, False, 100, False)


def test_load_command_suggestions_ranks_frequent_successful_commands(mocker, tmp_path):
    db = tmp_path / "history.db"
    _seed_metrics_db(db, [
        ("사파리 열어줘", True), ("사파리 열어줘", True), ("사파리 열어줘", True),
        ("볼륨 올려줘", True), ("볼륨 올려줘", True),
        ("날씨 알려줘", True),
    ])
    mocker.patch.dict("os.environ", {"VOICEDESK_DB": str(db)})
    assert _load_command_suggestions(limit=3) == ["사파리 열어줘", "볼륨 올려줘", "날씨 알려줘"]


def test_load_command_suggestions_pads_with_fallback_when_sparse(mocker, tmp_path):
    db = tmp_path / "history.db"
    _seed_metrics_db(db, [("사파리 열어줘", True)])
    mocker.patch.dict("os.environ", {"VOICEDESK_DB": str(db)})
    result = _load_command_suggestions(limit=3)
    assert result[0] == "사파리 열어줘"
    assert len(result) == 3
    # the padding comes from the curated fallback list (no duplicates)
    assert len(set(result)) == 3
    assert all(cmd in (["사파리 열어줘"] + list(_FALLBACK_SUGGESTIONS)) for cmd in result)


def test_load_command_suggestions_excludes_failed_and_blank(mocker, tmp_path):
    db = tmp_path / "history.db"
    _seed_metrics_db(db, [
        ("실패한 명령", False), ("실패한 명령", False),
        ("   ", True),
        ("성공한 명령", True),
    ])
    mocker.patch.dict("os.environ", {"VOICEDESK_DB": str(db)})
    result = _load_command_suggestions(limit=3)
    assert "실패한 명령" not in result
    assert result[0] == "성공한 명령"
    assert "   " not in result and "" not in result


def test_load_command_suggestions_falls_back_when_no_db(mocker, tmp_path):
    mocker.patch.dict("os.environ", {"VOICEDESK_DB": str(tmp_path / "missing.db")})
    assert _load_command_suggestions(limit=3) == list(_FALLBACK_SUGGESTIONS[:3])


def test_render_payload_includes_command_suggestions(mocker, tmp_path):
    db = tmp_path / "history.db"
    _seed_metrics_db(db, [("사파리 열어줘", True)])
    mocker.patch.dict("os.environ", {"VOICEDESK_DB": str(db)})
    hud = _isolated_hud()
    hud._pinned = True
    hud._state = "idle"
    payload = hud._render_payload()
    assert payload["commandSuggestions"][0] == "사파리 열어줘"
    assert len(payload["commandSuggestions"]) == 3


def test_render_payload_command_suggestions_empty_when_collapsed(mocker, tmp_path):
    """Like routines, suggestions query the DB only for the pinned panel — no
    metrics I/O on collapsed/listening/etc. renders that never show them."""
    db = tmp_path / "history.db"
    _seed_metrics_db(db, [("사파리 열어줘", True)])
    mocker.patch.dict("os.environ", {"VOICEDESK_DB": str(db)})
    hud = _isolated_hud()
    hud._pinned = False
    hud._state = "idle"
    payload = hud._render_payload()
    assert payload["commandSuggestions"] == []


def test_command_suggestion_event_runs_command_via_callback():
    hud = _isolated_hud()
    ran = []
    hud.set_run_command_callback(lambda cmd: ran.append(cmd))
    hud._on_swift_event({"event": "commandSuggestion", "command": "사파리 열어줘"})
    import time
    time.sleep(0.05)   # callback runs on a background thread
    assert ran == ["사파리 열어줘"]


def test_command_suggestion_event_noop_without_callback():
    hud = _isolated_hud()
    # No callback wired (e.g. before main() finishes setup) — must not raise.
    hud._on_swift_event({"event": "commandSuggestion", "command": "사파리 열어줘"})


def test_command_suggestion_event_ignores_blank():
    hud = _isolated_hud()
    ran = []
    hud.set_run_command_callback(lambda cmd: ran.append(cmd))
    hud._on_swift_event({"event": "commandSuggestion", "command": "   "})
    import time
    time.sleep(0.05)
    assert ran == []


def test_command_submit_event_runs_command_via_callback():
    hud = _isolated_hud()
    ran = []
    hud.set_run_command_callback(lambda cmd: ran.append(cmd))
    hud._on_swift_event({"event": "commandSubmit", "command": "텍스트로 실행해줘"})
    import time
    time.sleep(0.05)
    assert ran == ["텍스트로 실행해줘"]


def test_command_submit_event_ignores_blank():
    hud = _isolated_hud()
    ran = []
    hud.set_run_command_callback(lambda cmd: ran.append(cmd))
    hud._on_swift_event({"event": "commandSubmit", "command": "   "})
    import time
    time.sleep(0.05)
    assert ran == []


def test_run_routine_event_dispatches_and_speaks(mocker):
    hud = _isolated_hud()
    mock_dispatch = mocker.patch("agent.tools.dispatch", return_value="routine_done")
    mock_speak = mocker.patch("actions.tts.speak")

    hud._on_swift_event({"event": "runRoutine", "name": "출근 준비"})
    import time
    time.sleep(0.05)   # runs on a background thread

    mock_dispatch.assert_called_once_with("run_routine", {"name": "출근 준비"})
    mock_speak.assert_called_once()
    assert "출근 준비" in mock_speak.call_args.args[0]
    assert "실패" not in mock_speak.call_args.args[0]


def test_run_routine_event_speaks_failure_message(mocker):
    hud = _isolated_hud()
    mocker.patch("agent.tools.dispatch", return_value="routine_failed")
    mock_speak = mocker.patch("actions.tts.speak")

    hud._on_swift_event({"event": "runRoutine", "name": "없는루틴"})
    import time
    time.sleep(0.05)

    mock_speak.assert_called_once()
    assert "실패" in mock_speak.call_args.args[0]


def test_run_routine_event_ignores_blank_name(mocker):
    hud = _isolated_hud()
    mock_dispatch = mocker.patch("agent.tools.dispatch")
    hud._on_swift_event({"event": "runRoutine", "name": "  "})
    mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# Media transport controls (prev/play-pause/next) wired to real playback
# ---------------------------------------------------------------------------

def test_media_next_event_sends_applescript_to_active_player(mocker):
    hud = _isolated_hud()
    hud._media = ("Song", "Artist", "Spotify", True)
    mock_run = mocker.patch("actions.applescript.run_applescript")
    mocker.patch.object(hud, "_fetch_media_async")

    hud._on_swift_event({"event": "mediaNext"})
    import time
    time.sleep(0.05)

    mock_run.assert_called_once_with('tell application "Spotify" to next track')


def test_media_prev_event_sends_applescript(mocker):
    hud = _isolated_hud()
    hud._media = ("Song", "Artist", "Music", True)
    mock_run = mocker.patch("actions.applescript.run_applescript")
    mocker.patch.object(hud, "_fetch_media_async")

    hud._on_swift_event({"event": "mediaPrev"})
    import time
    time.sleep(0.05)

    mock_run.assert_called_once_with('tell application "Music" to previous track')


def test_media_play_pause_event_sends_applescript(mocker):
    hud = _isolated_hud()
    hud._media = ("Song", "Artist", "Music", True)
    mock_run = mocker.patch("actions.applescript.run_applescript")
    mocker.patch.object(hud, "_fetch_media_async")

    hud._on_swift_event({"event": "mediaPlayPause"})
    import time
    time.sleep(0.05)

    mock_run.assert_called_once_with('tell application "Music" to playpause')


def test_media_control_refetches_after_command(mocker):
    """A track/prev/next command changes the track — the panel must refresh
    afterward instead of showing stale info until the next 5s tick."""
    hud = _isolated_hud()
    hud._media = ("Song", "Artist", "Music", True)
    mocker.patch("actions.applescript.run_applescript")
    mock_fetch = mocker.patch.object(hud, "_fetch_media_async")

    hud._on_swift_event({"event": "mediaNext"})
    import time
    time.sleep(0.4)   # command's own 0.3s settle delay + margin

    mock_fetch.assert_called_once()


def test_media_control_noop_when_nothing_playing(mocker):
    hud = _isolated_hud()
    hud._media = None
    mock_run = mocker.patch("actions.applescript.run_applescript")
    hud._on_swift_event({"event": "mediaNext"})
    mock_run.assert_not_called()


def test_media_seek_event_sets_player_position(mocker):
    hud = _isolated_hud()
    hud._media = ("Song", "Artist", "Music", True, 10.0, 210.0)
    mock_run = mocker.patch("actions.applescript.run_applescript")
    mocker.patch.object(hud, "_fetch_media_async")

    hud._on_swift_event({"event": "mediaSeek", "position": 42.5})
    import time
    time.sleep(0.05)

    mock_run.assert_called_once_with('tell application "Music" to set player position to 42.50')


def test_media_seek_noop_when_nothing_playing(mocker):
    hud = _isolated_hud()
    hud._media = None
    mock_run = mocker.patch("actions.applescript.run_applescript")
    hud._on_swift_event({"event": "mediaSeek", "position": 42.5})
    import time
    time.sleep(0.05)
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Calendar todos: parsing, next-event, store, and the Swift event round-trip
# ---------------------------------------------------------------------------

from ui.notch_hud import _parse_todo_input, _next_event, TodoStore


def test_parse_todo_input_hhmm():
    assert _parse_todo_input("회의 14:00") == ("회의", "14:00")
    assert _parse_todo_input("보고서 초안 작성 09:05") == ("보고서 초안 작성", "09:05")


def test_parse_todo_input_korean_time():
    assert _parse_todo_input("점심 오후 2시") == ("점심", "14:00")
    assert _parse_todo_input("운동 오전 9시 30분") == ("운동", "09:30")
    assert _parse_todo_input("점심 12시") == ("점심", "12:00")
    assert _parse_todo_input("자정 오전 12시") == ("자정", "00:00")


def test_parse_todo_input_no_time():
    assert _parse_todo_input("우유 사기") == ("우유 사기", "")
    # A bare time with no text stays as text, not a timeless empty todo.
    assert _parse_todo_input("14:00") == ("14:00", "")
    # Out-of-range minutes aren't a valid deadline → kept verbatim.
    assert _parse_todo_input("회의 25:99") == ("회의 25:99", "")


def test_parse_todo_input_empty():
    assert _parse_todo_input("") == ("", "")
    assert _parse_todo_input("   ") == ("", "")


def test_next_event_picks_earliest_future_deadline():
    todos = [
        {"date": "2026-07-14", "time": "14:00", "text": "A", "done": False},
        {"date": "2026-07-14", "time": "15:00", "text": "B", "done": False},
        {"date": "2026-07-14", "time": "", "text": "untimed", "done": False},
    ]
    assert _next_event(todos, "2026-07-14", 13 * 60 + 59) == ("A", "14:00")
    # At exactly 14:00 the 14:00 item stops being "next"; 15:00 takes over.
    assert _next_event(todos, "2026-07-14", 14 * 60) == ("B", "15:00")
    assert _next_event(todos, "2026-07-14", 15 * 60) == ("", "")


def test_next_event_ignores_other_days_and_done():
    todos = [
        {"date": "2026-07-15", "time": "10:00", "text": "tomorrow", "done": False},
        {"date": "2026-07-14", "time": "10:00", "text": "done", "done": True},
        {"date": "2026-07-14", "time": "11:00", "text": "live", "done": False},
    ]
    assert _next_event(todos, "2026-07-14", 8 * 60) == ("live", "11:00")


def test_todo_store_crud_and_persistence(tmp_path):
    path = str(tmp_path / "todos.json")
    store = TodoStore(path)
    item = store.add("2026-07-14", "치과 예약", "10:30")
    assert item["text"] == "치과 예약" and item["time"] == "10:30" and not item["done"]

    assert store.toggle(item["id"]) is True
    assert store.get(item["id"])["done"] is True

    assert store.update(item["id"], "치과 검진", "11:00") is True
    got = store.get(item["id"])
    assert got["text"] == "치과 검진" and got["time"] == "11:00"

    # Survives reload from disk.
    reloaded = TodoStore(path)
    assert len(reloaded.all()) == 1

    assert store.delete(item["id"]) is True
    assert store.get(item["id"]) is None
    assert store.delete("missing") is False


def test_todo_store_missing_file_is_empty(tmp_path):
    assert TodoStore(str(tmp_path / "nope.json")).all() == []


def test_todo_toggle_and_delete_events_mutate_store(tmp_path):
    hud = _isolated_hud()
    hud._todos = TodoStore(str(tmp_path / "todos.json"))
    item = hud._todos.add("2026-07-14", "일", "")
    rendered = []
    hud._render = lambda: rendered.append(1)

    hud._on_swift_event({"event": "todoToggle", "id": item["id"]})
    assert hud._todos.get(item["id"])["done"] is True

    hud._on_swift_event({"event": "todoDelete", "id": item["id"]})
    assert hud._todos.get(item["id"]) is None
    assert len(rendered) == 2


def test_calendar_select_and_shift_events_update_state():
    hud = _isolated_hud()
    hud._render = lambda: None
    hud._on_swift_event({"event": "calendarSelectDay", "date": "2026-08-01"})
    assert hud._cal_selected_date == "2026-08-01"

    hud._cal_month_offset = 0
    hud._on_swift_event({"event": "calendarShiftMonth", "delta": 1})
    assert hud._cal_month_offset == 1
    hud._on_swift_event({"event": "calendarShiftMonth", "delta": -2})
    assert hud._cal_month_offset == -1


def test_todo_add_event_parses_and_appends(tmp_path):
    hud = _isolated_hud()
    hud._todos = TodoStore(str(tmp_path / "todos.json"))
    rendered = []
    hud._render = lambda: rendered.append(1)

    hud._on_swift_event({"event": "todoAdd", "date": "2026-07-14", "text": "회의 14:00"})
    items = hud._todos.all()
    assert len(items) == 1
    assert items[0]["text"] == "회의" and items[0]["time"] == "14:00"
    assert items[0]["date"] == "2026-07-14"
    assert rendered == [1]


def test_todo_add_event_ignores_empty_text(tmp_path):
    hud = _isolated_hud()
    hud._todos = TodoStore(str(tmp_path / "todos.json"))
    hud._render = lambda: None
    hud._on_swift_event({"event": "todoAdd", "date": "2026-07-14", "text": "   "})
    assert hud._todos.all() == []


def test_todo_update_event_rewrites_existing(tmp_path):
    hud = _isolated_hud()
    hud._todos = TodoStore(str(tmp_path / "todos.json"))
    hud._render = lambda: None
    item = hud._todos.add("2026-07-14", "old", "09:00")

    hud._on_swift_event({"event": "todoUpdate", "id": item["id"], "text": "새 할일 10:30"})
    got = hud._todos.get(item["id"])
    assert got["text"] == "새 할일" and got["time"] == "10:30"


def test_todo_update_event_empty_text_keeps_original(tmp_path):
    hud = _isolated_hud()
    hud._todos = TodoStore(str(tmp_path / "todos.json"))
    hud._render = lambda: None
    item = hud._todos.add("2026-07-14", "keep", "09:00")

    hud._on_swift_event({"event": "todoUpdate", "id": item["id"], "text": ""})
    got = hud._todos.get(item["id"])
    assert got["text"] == "keep" and got["time"] == "09:00"


def test_inline_edit_begin_end_toggle_keyboard_focus():
    hud = _isolated_hud()
    calls = []
    hud._render = lambda: calls.append(1)

    hud._on_swift_event({"event": "inlineEditBegin"})
    assert hud._keyboard_active is True
    # A duplicate begin doesn't re-render.
    hud._on_swift_event({"event": "inlineEditBegin"})
    assert len(calls) == 1

    hud._on_swift_event({"event": "inlineEditEnd"})
    assert hud._keyboard_active is False
    assert len(calls) == 2


def test_keyboard_focus_cleared_on_state_change_and_collapse():
    hud = _isolated_hud()
    hud._render = lambda: None
    # A voice command activating a non-idle state drops inline keyboard focus.
    hud._keyboard_active = True
    hud.set_state("listening")
    assert hud._keyboard_active is False

    # Collapsing the pinned panel also closes the inline field.
    hud._state = "idle"
    hud._pinned = True
    hud._keyboard_active = True
    hud._toggle_pin()   # unpin
    assert hud._pinned is False
    assert hud._keyboard_active is False


def test_render_payload_carries_keyboard_active_flag(mocker):
    hud = _isolated_hud()
    mocker.patch.object(hud, "_arm_widget_tick")
    hud._pinned = True
    hud._state = "idle"
    hud._keyboard_active = True
    assert hud._render_payload()["keyboardActive"] is True
    hud._keyboard_active = False
    assert hud._render_payload()["keyboardActive"] is False


def test_request_text_input_restores_pinned_panel():
    import threading
    hud = _isolated_hud()
    hud._pinned = True
    hud._state = "idle"

    def submit():
        _wait_until_text_request_ready(hud)
        hud._on_swift_event({"event": "textSubmit", "text": "x"})

    threading.Thread(target=submit, daemon=True).start()
    value = hud.request_text_input("할 일 입력", "", timeout=2.0)
    assert value == "x"
    # The panel returns to the open pinned state, not a collapsed notch.
    assert hud._pinned is True
    assert hud._state == "idle"


def test_render_payload_includes_todos_and_calendar_when_pinned(mocker, tmp_path):
    hud = _isolated_hud()
    hud._todos = TodoStore(str(tmp_path / "todos.json"))
    hud._pinned = True
    hud._state = "idle"
    mocker.patch.object(hud, "_arm_widget_tick")
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    hud._todos.add(today, "할일", "23:59")

    payload = hud._render_payload()
    assert any(t["text"] == "할일" for t in payload["todos"])
    assert payload["calSelectedDate"] == hud._cal_selected_date
    assert payload["calMonthOffset"] == hud._cal_month_offset
    assert "nextEventTitle" in payload and "nextEventTime" in payload


def test_render_payload_omits_todos_when_not_pinned():
    hud = _isolated_hud()
    hud._pinned = False
    hud._state = "idle"
    payload = hud._render_payload()
    assert payload["todos"] == []
    assert payload["nextEventTitle"] == "" and payload["nextEventTime"] == ""


# ---------------------------------------------------------------------------
# Screen-control indicator
# ---------------------------------------------------------------------------

class _FakeBridge:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)
        return True


def _control_hud():
    hud = _isolated_hud()
    hud._bridge = _FakeBridge()
    return hud


def test_set_screen_control_sends_control_message():
    hud = _control_hud()
    hud.set_screen_control(True)
    assert {"type": "control", "on": True} in hud._bridge.sent


def test_set_screen_control_dedupes_repeat_calls():
    hud = _control_hud()
    hud.set_screen_control(True)
    hud.set_screen_control(True)
    assert hud._bridge.sent.count({"type": "control", "on": True}) == 1


def test_screen_control_cleared_when_leaving_executing():
    hud = _control_hud()
    hud.set_state("executing")
    hud.set_screen_control(True)
    hud.set_state("success")
    assert {"type": "control", "on": False} in hud._bridge.sent


def test_screen_control_kept_while_still_executing():
    hud = _control_hud()
    hud.set_state("executing")
    hud.set_screen_control(True)
    hud.set_state("executing")
    assert {"type": "control", "on": False} not in hud._bridge.sent


def test_set_state_without_control_sends_nothing_extra():
    hud = _control_hud()
    hud.set_state("idle")
    assert all(p.get("type") != "control" for p in hud._bridge.sent)
