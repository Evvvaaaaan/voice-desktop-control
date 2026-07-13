import re
import os
import sys
from urllib.parse import urlsplit, urlunsplit, quote, parse_qsl, urlencode
from actions import accessibility
from actions.applescript import run_applescript
from actions.mouse_keyboard import (
    click, double_click, move_mouse, type_text, press_key, scroll,
)
from actions.screen import take_screenshot_with_grid, active_screen_rect, last_capture_rect

_SAFE_APP_NAME = re.compile(r'^[A-Za-z0-9가-힣 ._-]+$')
# Only http(s) URLs, and no characters that could break out of the quoted
# AppleScript string ("  '  \  <  >  and whitespace).
_SAFE_URL = re.compile(r'^https?://[^\s"\'\\<>]+$')


def _percent_encode_url(url: str) -> str:
    """AppleScript's `open location` (the generic, no-app-specified path)
    mangles raw non-ASCII bytes into mojibake — e.g. a Korean search query
    comes out as garbage in the browser's address bar. Percent-encoding the
    path/query/fragment to plain ASCII before it ever reaches osascript
    sidesteps that entirely."""
    parts = urlsplit(url)
    path = quote(parts.path, safe="/%")
    query = urlencode(parse_qsl(parts.query, keep_blank_values=True))
    fragment = quote(parts.fragment, safe="%")
    return urlunsplit((parts.scheme, parts.netloc, path, query, fragment))

# The vision model reports pointer targets in a resolution-independent
# 0..1000 grid (top-left origin) so its coordinates survive screenshot
# downscaling; we map that grid onto the display's logical points here.
_COORD_SCALE = 1000.0

# Long text is unreliable when dictated: anything this long is routed to the
# notch text field (prefilled with the LLM's draft) for the user to confirm
# or fix with the keyboard before it is typed.
_TEXT_INPUT_MIN_CHARS = 10
_TEXT_INPUT_PROVIDER = None   # hud.request_text_input, wired by main()


def set_text_input_provider(provider) -> None:
    global _TEXT_INPUT_PROVIDER
    _TEXT_INPUT_PROVIDER = provider


def _to_logical(params):
    """Map normalized (0..1000) x/y to global screen points on the display
    the last screenshot actually captured. Global coordinates may be negative
    on multi-display setups (screens left of / above the main one).

    Uses last_capture_rect() rather than a fresh active_screen_rect() call:
    on a multi-monitor Mac, re-resolving "the active display" at click time
    can disagree with what was resolved at screenshot time (a focus change
    mid-turn, or a region-capture failure that silently fell back to the
    main display — see _capture_active_display_png) and send the click to a
    different display than the one the model was actually shown. Falls back
    to active_screen_rect() only if no screenshot has been taken yet.

    Clamped just inside that display so a stray corner value never trips
    pyautogui's failsafe. Returns (x, y) or None if a coordinate is missing."""
    raw_x, raw_y = params.get("x"), params.get("y")
    if raw_x is None or raw_y is None:
        return None
    try:
        nx, ny = float(raw_x), float(raw_y)
    except (TypeError, ValueError):
        return None
    rx, ry, rw, rh = last_capture_rect() or active_screen_rect()
    x = rx + nx / _COORD_SCALE * rw
    y = ry + ny / _COORD_SCALE * rh
    x = max(rx + 1, min(rx + rw - 2, x))
    y = max(ry + 1, min(ry + rh - 2, y))
    return int(x), int(y)


class _DispatchExecutor:
    def run(self, action: str, params: dict) -> bool:
        return bool(dispatch(action, params))


def dispatch(action: str, params: dict) -> str:
    if action == "launch_app":
        app = str(params.get("app", params.get("app_name", params.get("name", ""))) or "")
        if not _SAFE_APP_NAME.match(app):
            return f"error: invalid app name: {app}"
        res = run_applescript(f'tell application "{app}" to activate')
        if not res.startswith("error"):
            # Pin the launched app as the command's target so later
            # read_screen/click_element keep driving it even when the user
            # focuses another window.
            try:
                accessibility.set_target_app(app)
            except Exception:
                pass
        return res
    elif action == "open_url":
        url = str(params.get("url", "") or "")
        if not _SAFE_URL.match(url):
            return f"error: invalid url: {url}"
        url = _percent_encode_url(url)
        browser = str(params.get("browser", "") or "")
        if browser:
            if not _SAFE_APP_NAME.match(browser):
                return f"error: invalid browser: {browser}"
            return run_applescript(f'tell application "{browser}" to open location "{url}"')
        return run_applescript(f'open location "{url}"')
    elif action == "click":
        pt = _to_logical(params)
        if pt is None:
            return "error: click requires params x and y"
        click(*pt)
        print(f"[ComputerUse] Clicked at {pt[0]},{pt[1]}", file=sys.stderr)
        return f"clicked at {pt[0]},{pt[1]}"
    elif action == "double_click":
        pt = _to_logical(params)
        if pt is None:
            return "error: double_click requires params x and y"
        double_click(*pt)
        print(f"[ComputerUse] Double-clicked at {pt[0]},{pt[1]}", file=sys.stderr)
        return f"double_clicked at {pt[0]},{pt[1]}"
    elif action == "move_mouse":
        pt = _to_logical(params)
        if pt is None:
            return "error: move_mouse requires params x and y"
        move_mouse(*pt)
        print(f"[ComputerUse] Moved mouse to {pt[0]},{pt[1]}", file=sys.stderr)
        return f"moved to {pt[0]},{pt[1]}"
    elif action == "type_text":
        text = params.get("text")
        if not text:
            return "error: type_text requires param text"
        if len(text) >= _TEXT_INPUT_MIN_CHARS and _TEXT_INPUT_PROVIDER is not None:
            confirmed = _TEXT_INPUT_PROVIDER(
                "입력할 내용을 확인하거나 수정한 뒤 Enter를 눌러 주세요", text
            )
            if confirmed is None:
                return "error: 사용자가 텍스트 입력을 취소했습니다"
            text = confirmed
        type_text(text)
        print(f"[ComputerUse] Typed: {text!r}", file=sys.stderr)
        return "typed"
    elif action == "press_key":
        key = params.get("key")
        if not key:
            return "error: press_key requires param key"
        press_key(key)
        print(f"[ComputerUse] Pressed key: {key}", file=sys.stderr)
        return "pressed"
    elif action == "scroll":
        # Position is optional; scroll at the current pointer if not given.
        pt = _to_logical(params) or (0, 0)
        direction = params.get("direction", "down")
        amount = params.get("amount", 3)
        scroll(pt[0], pt[1], direction, amount)
        print(f"[ComputerUse] Scrolled {direction} x{amount} at {pt[0]},{pt[1]}", file=sys.stderr)
        return "scrolled"
    elif action == "run_applescript":
        script = params.get("script")
        if not script:
            return "error: run_applescript requires param script"
        return run_applescript(script)
    elif action == "read_screen":
        return accessibility.snapshot_screen()
    elif action == "click_element":
        try:
            element_id = int(params.get("id"))
        except (TypeError, ValueError):
            return "error: click_element requires integer param id"
        if not accessibility.element_known(element_id):
            return (f"error: 알 수 없는 요소 id {element_id} — "
                    "read_screen을 먼저 실행하세요")
        pressed = accessibility.press_element(element_id, bool(params.get("double")))
        if pressed is not None:
            return pressed
        # No usable AX action — real mouse click is the one element path
        # that still interferes with the user's pointer.
        center = accessibility.element_center(element_id)
        if center is None:
            return (f"error: 요소 {element_id}가 더 이상 존재하지 않아요 — "
                    "read_screen으로 다시 확인하세요")
        x, y = int(center[0]), int(center[1])
        if params.get("double"):
            double_click(x, y)
            return f"double_clicked element {element_id} at {x},{y} (mouse fallback)"
        click(x, y)
        return f"clicked element {element_id} at {x},{y} (mouse fallback)"
    elif action == "set_value":
        try:
            element_id = int(params.get("id"))
        except (TypeError, ValueError):
            return "error: set_value requires integer param id"
        text = params.get("text")
        if text is None:
            return "error: set_value requires param text"
        text = str(text)
        if len(text) >= _TEXT_INPUT_MIN_CHARS and _TEXT_INPUT_PROVIDER is not None:
            confirmed = _TEXT_INPUT_PROVIDER(
                "입력할 내용을 확인하거나 수정한 뒤 Enter를 눌러 주세요", text
            )
            if confirmed is None:
                return "error: 사용자가 텍스트 입력을 취소했습니다"
            text = confirmed
        return accessibility.set_element_value(element_id, text)
    elif action == "screenshot":
        return f"screenshot_taken:{len(take_screenshot_with_grid())} bytes"
    elif action == "speak_only":
        return ""
    elif action == "run_routine":
        from routines.manager import RoutineManager
        mgr = RoutineManager(os.environ.get("VOICEDESK_ROUTINES", "data/routines.json"))
        name = params.get("name", "")
        success = mgr.execute(name, _DispatchExecutor())
        return "routine_done" if success else "routine_failed"
    else:
        return f"unknown_action:{action}"
