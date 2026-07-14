import re
import os
import pwd
import sys
import shlex
import shutil
import subprocess
from urllib.parse import urlsplit, urlunsplit, quote, parse_qsl, urlencode
from actions import accessibility
from actions.applescript import run_applescript
from actions.mouse_keyboard import (
    click, double_click, move_mouse, type_text, press_key, scroll,
)
from actions.screen import take_screenshot_with_grid, active_screen_rect, last_capture_rect

_SAFE_APP_NAME = re.compile(r'^[A-Za-z0-9가-힣 ._-]+$')
# A single folder name — no path separators or traversal. Kept deliberately
# strict so it can be joined onto a trusted base directory without escaping.
_SAFE_PROJECT_NAME = re.compile(r'^[A-Za-z0-9가-힣 ._-]+$')
# Where new_project may create folders — a small whitelist of writable,
# Finder-visible locations under the user's real home. Keyed by the lowercased
# value the model passes; "" / "home" mean the home directory itself.
_PROJECT_BASES = {
    "": "", "home": "", "홈": "",
    "desktop": "Desktop", "바탕화면": "Desktop",
    "documents": "Documents", "문서": "Documents",
    "downloads": "Downloads", "다운로드": "Downloads",
}


def _user_home() -> str:
    """The login user's real home directory, read from the password database
    rather than $HOME. A GUI-launched .app (Finder/DMG) can inherit an empty
    or wrong HOME and a read-only working directory (/), which made a shelled
    `mkdir -p ~/...` fail with "read-only directory". getpwuid is immune to
    that — it resolves the home the same way regardless of the environment."""
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except Exception:
        return os.path.expanduser("~")


def _project_path(name: str, base_key: str) -> str:
    """Absolute path of a project folder, from a validated name + base key.
    Shared by new_project (which creates it) and run_claude (which runs inside
    it) so the two resolve to the exact same directory for the same params."""
    sub = _PROJECT_BASES[base_key]
    base_dir = os.path.join(_user_home(), sub) if sub else _user_home()
    return os.path.join(base_dir, name)
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


_CONTROL_INDICATOR = None   # hud.set_screen_control, wired by main()


def set_control_indicator_provider(provider) -> None:
    global _CONTROL_INDICATOR
    _CONTROL_INDICATOR = provider


def _signal_screen_control() -> None:
    """Tell the HUD the agent is about to drive the real pointer. The HUD
    clears the indicator itself when the command leaves the executing state."""
    if _CONTROL_INDICATOR is None:
        return
    try:
        _CONTROL_INDICATOR(True)
    except Exception:
        pass


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
        raw_url = str(params.get("url", "") or "")
        # Percent-encode BEFORE validating: a URL that carries spaces or
        # non-ASCII in its path/query (a Google query, a Gmail compose body
        # with real Korean text and spaces) would otherwise be rejected
        # outright by _SAFE_URL. Encoding turns those into safe %XX/+ groups
        # first; the netloc is left untouched, so the post-encode _SAFE_URL
        # check still blocks any AppleScript-injection payload (embedded
        # quotes/backslashes/spaces in the host) exactly as before.
        try:
            url = _percent_encode_url(raw_url)
        except Exception:
            return f"error: invalid url: {raw_url}"
        if not _SAFE_URL.match(url):
            return f"error: invalid url: {raw_url}"
        browser = str(params.get("browser", "") or "")
        if browser:
            if not _SAFE_APP_NAME.match(browser):
                return f"error: invalid browser: {browser}"
            return run_applescript(f'tell application "{browser}" to open location "{url}"')
        return run_applescript(f'open location "{url}"')
    elif action == "new_project":
        # Deterministic folder-scaffold step: make a project directory under
        # the user's real home and open it in an editor (VS Code by default,
        # as a workspace so its integrated terminal starts in that folder).
        # Doing this in-process — os.makedirs + `open` — instead of a shelled
        # `mkdir -p ~/...` sidesteps the HOME/cwd fragility that made the
        # shell path fail with "read-only directory" inside a packaged .app.
        name = str(params.get("name", "") or "").strip()
        if not name or name in (".", "..") or not _SAFE_PROJECT_NAME.match(name):
            return f"error: invalid project name: {name}"
        base_key = str(params.get("base", "") or "").strip().lower()
        if base_key not in _PROJECT_BASES:
            return (f"error: invalid base: {base_key} — "
                    "use desktop/documents/downloads/home")
        editor = str(params.get("editor", "Visual Studio Code")
                     or "Visual Studio Code")
        if not _SAFE_APP_NAME.match(editor):
            return f"error: invalid editor: {editor}"
        path = _project_path(name, base_key)
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            return f"error: 폴더를 만들 수 없습니다: {e}"
        try:
            # `open -a <editor> <folder>` opens the folder as a workspace; no
            # shell, so path spaces are safe and SafetyGuard isn't triggered.
            subprocess.run(["open", "-a", editor, path],
                           check=True, capture_output=True, timeout=15)
        except Exception as e:
            return (f"error: 폴더는 만들었지만 {editor}로 열지 못했어요 "
                    f"({path}): {e}")
        return f"created and opened {path} in {editor}"
    elif action == "run_claude":
        # Run Claude Code (`claude -p`) inside VS Code's INTEGRATED TERMINAL of
        # the already-open project, so the user watches it work in the same
        # editor window. new_project opened the folder as a workspace, so a new
        # integrated terminal starts in that folder. We drive VS Code via
        # System Events: focus it, open a new terminal, and run a launcher.
        prompt = str(params.get("prompt", "") or "").strip()
        if not prompt:
            return "error: run_claude requires param prompt"
        name = str(params.get("name", "") or "").strip()
        if not name or name in (".", "..") or not _SAFE_PROJECT_NAME.match(name):
            return f"error: invalid project name: {name}"
        base_key = str(params.get("base", "desktop") or "desktop").strip().lower()
        if base_key not in _PROJECT_BASES:
            return (f"error: invalid base: {base_key} — "
                    "use desktop/documents/downloads/home")
        path = _project_path(name, base_key)
        if not os.path.isdir(path):
            return (f"error: 프로젝트 폴더가 없어요 ({path}) — "
                    "먼저 new_project로 폴더를 만드세요")
        claude_bin = shutil.which("claude") or os.path.join(
            _user_home(), ".local", "bin", "claude")
        if not os.path.exists(claude_bin):
            return ("error: claude CLI를 찾을 수 없어요 — "
                    "Claude Code가 설치되어 있는지 확인하세요")
        # Run Claude in NON-INTERACTIVE print mode (`claude -p`): it executes
        # the prompt and streams progress in the terminal, then exits — no TUI
        # to navigate. Interactive `claude` instead lands on a one-time "Bypass
        # Permissions? [No/Yes]" screen that a blind paste+Enter can't answer
        # (it defaulted to "No, exit" and quit). Put the Korean prompt and the
        # (possibly non-ASCII) project path in a FIXED-ASCII launcher script so
        # the only thing typed into the terminal is `sh ~/...` — no unreliable
        # Unicode keystrokes, no quote-escaping across paste, no dependence on
        # the terminal's starting directory. shlex.quote keeps prompt + path
        # safe as single argv tokens.
        launcher = os.path.join(_user_home(), ".voicedesk_run_claude.sh")
        script_body = (
            "#!/bin/sh\n"
            f"cd {shlex.quote(path)} || exit 1\n"
            f"exec {shlex.quote(claude_bin)} -p {shlex.quote(prompt)} "
            "--permission-mode bypassPermissions\n"
        )
        try:
            with open(launcher, "w") as fh:
                fh.write(script_body)
            os.chmod(launcher, 0o755)
        except OSError as e:
            return f"error: 실행 스크립트를 만들지 못했어요: {e}"
        # Static ASCII AppleScript — no user input is interpolated here. New
        # integrated terminal via the default SHORTCUT (Control+Shift+`, key
        # code 50 — locale-independent, unlike the menu whose title is
        # localized to "터미널"), then run the launcher. `key code 36` is Return.
        applescript = (
            'tell application "Visual Studio Code" to activate\n'
            'delay 1.0\n'
            'tell application "System Events"\n'
            '    key code 50 using {control down, shift down}\n'
            '    delay 1.0\n'
            '    keystroke "sh ~/.voicedesk_run_claude.sh"\n'
            '    key code 36\n'
            'end tell'
        )
        result = run_applescript(applescript)
        if isinstance(result, str) and result.startswith("error:"):
            return ("error: VS Code 통합 터미널에서 Claude를 실행하지 못했어요 "
                    f"(손쉬운 사용 권한을 확인하세요): {result[6:].strip()}")
        return (f"started Claude in VS Code integrated terminal for {path} — "
                "VS Code 터미널에서 작업이 진행되는 걸 확인하세요")
    elif action == "click":
        pt = _to_logical(params)
        if pt is None:
            return "error: click requires params x and y"
        _signal_screen_control()
        click(*pt)
        print(f"[ComputerUse] Clicked at {pt[0]},{pt[1]}", file=sys.stderr)
        return f"clicked at {pt[0]},{pt[1]}"
    elif action == "double_click":
        pt = _to_logical(params)
        if pt is None:
            return "error: double_click requires params x and y"
        _signal_screen_control()
        double_click(*pt)
        print(f"[ComputerUse] Double-clicked at {pt[0]},{pt[1]}", file=sys.stderr)
        return f"double_clicked at {pt[0]},{pt[1]}"
    elif action == "move_mouse":
        pt = _to_logical(params)
        if pt is None:
            return "error: move_mouse requires params x and y"
        _signal_screen_control()
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
        _signal_screen_control()
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
        _signal_screen_control()
        # A real mouse click lands on the topmost window at the point, so
        # the target app must be frontmost before the glide starts.
        try:
            accessibility.activate_target_app()
        except Exception:
            pass
        center = accessibility.element_center(element_id)
        if center is None:
            return (f"error: 요소 {element_id}가 더 이상 존재하지 않아요 — "
                    "read_screen으로 다시 확인하세요")
        x, y = int(center[0]), int(center[1])
        if params.get("double"):
            double_click(x, y)
            return f"double_clicked element {element_id} at {x},{y}"
        click(x, y)
        return f"clicked element {element_id} at {x},{y}"
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
