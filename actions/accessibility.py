import subprocess
import time


def click_element_by_name(app_name: str, element_name: str) -> bool:
    script = f'''
    tell application "{app_name}"
        activate
    end tell
    tell application "System Events"
        tell process "{app_name}"
            click button "{element_name}" of window 1
        end tell
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


# ---------- AX window-use snapshot ----------
# The LLM reads the frontmost app's Accessibility tree as a numbered element
# list (read_screen) and clicks by element id (click_element) — the macOS
# equivalent of claude-in-chrome's read_page. Coordinates come from AX, not
# from a vision model's guess, so clicks land exactly and non-vision LLMs
# can control the screen.

_INTERACTIVE_ROLES = {
    "AXButton", "AXLink", "AXTextField", "AXTextArea", "AXCheckBox",
    "AXRadioButton", "AXPopUpButton", "AXComboBox", "AXMenuButton",
    "AXMenuItem", "AXSlider", "AXDisclosureTriangle", "AXTabGroup",
}

_ROLE_KO = {
    "AXButton": "버튼", "AXLink": "링크", "AXTextField": "텍스트필드",
    "AXTextArea": "텍스트영역", "AXCheckBox": "체크박스",
    "AXRadioButton": "라디오버튼", "AXPopUpButton": "팝업버튼",
    "AXComboBox": "콤보박스", "AXMenuButton": "메뉴버튼",
    "AXMenuItem": "메뉴항목", "AXSlider": "슬라이더",
    "AXDisclosureTriangle": "펼침삼각형", "AXTabGroup": "탭그룹",
}

# Hard caps keep a pathological tree (endless web page) from stalling the
# voice loop; probe_ax.py measured typical apps well inside these.
_MAX_VISITED = 6000
_MAX_DEPTH = 25
_MAX_ELEMENTS = 150
_MAX_WINDOWS = 2
_MIN_ELEMENTS_FOR_AX = 5
_TITLE_MAX = 40
_AX_TIMEOUT_SEC = 0.3
_CHROMIUM_SETTLE_SEC = 0.3

# id -> AXUIElement of the LATEST read_screen. Replaced wholesale on every
# snapshot, so stale ids from an older screen can never be clicked.
_SNAPSHOT: dict[int, object] = {}


def _ax_trusted() -> bool:
    import ApplicationServices as AS
    return bool(AS.AXIsProcessTrusted())


def _frontmost_app():
    """(localized name, pid) of the frontmost app, or (None, None)."""
    import AppKit
    front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    if front is None:
        return None, None
    return str(front.localizedName()), int(front.processIdentifier())


def _ax_app(pid: int):
    import ApplicationServices as AS
    app = AS.AXUIElementCreateApplication(pid)
    AS.AXUIElementSetMessagingTimeout(app, _AX_TIMEOUT_SEC)
    # Chromium/Electron apps only build the web-content AX tree when
    # assistive tech announces itself; both spellings span app generations.
    for flag in ("AXEnhancedUserInterface", "AXManualAccessibility"):
        AS.AXUIElementSetAttributeValue(app, flag, True)
    time.sleep(_CHROMIUM_SETTLE_SEC)
    return app


def _ax_attr(elem, name):
    import ApplicationServices as AS
    err, val = AS.AXUIElementCopyAttributeValue(elem, name, None)
    return val if err == 0 else None


def _ax_center(elem):
    """Global (x, y) center of the element; None when it has no usable
    geometry (zero size, or the element no longer exists)."""
    import ApplicationServices as AS
    pos = _ax_attr(elem, "AXPosition")
    size = _ax_attr(elem, "AXSize")
    if pos is None or size is None:
        return None
    okp, p = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
    oks, s = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
    if not (okp and oks) or s.width <= 0 or s.height <= 0:
        return None
    return (p.x + s.width / 2.0, p.y + s.height / 2.0)


def snapshot_screen() -> str:
    """Walk the frontmost app's AX tree into a numbered interactive-element
    list. Repopulates the id snapshot; all previous ids become invalid."""
    global _TARGET_PID, _TARGET_NAME
    _SNAPSHOT.clear()
    if not _ax_trusted():
        return ("error: 접근성 권한이 없어요 — 시스템 설정 → 개인정보 보호 및 보안 → "
                "손쉬운 사용에서 VoiceDesk를 허용해 주세요")
    name, pid = _TARGET_NAME, _TARGET_PID
    if pid is not None and all(p != pid for _, p in _running_apps()):
        return f"error: 대상 앱({name})이 종료되었어요 — 앱을 다시 실행해 주세요"
    if pid is None:
        name, pid = _frontmost_app()
        if pid is None:
            return "error: 활성 앱을 찾을 수 없어요"
        _TARGET_PID, _TARGET_NAME = pid, name
    try:
        app = _ax_app(pid)
        windows = list(_ax_attr(app, "AXWindows") or [])[:_MAX_WINDOWS]
        entries = []   # (elem, role, title, value)
        visited = 0
        for w in windows:
            stack = [(w, 0)]
            while stack and visited < _MAX_VISITED and len(entries) < _MAX_ELEMENTS:
                elem, depth = stack.pop()
                if depth > _MAX_DEPTH:
                    continue
                visited += 1
                role = _ax_attr(elem, "AXRole")
                if role in _INTERACTIVE_ROLES and _ax_center(elem) is not None:
                    title = (_ax_attr(elem, "AXTitle")
                             or _ax_attr(elem, "AXDescription") or "")
                    value = _ax_attr(elem, "AXValue")
                    entries.append((
                        elem, role, str(title)[:_TITLE_MAX],
                        "" if value is None else str(value)[:_TITLE_MAX],
                    ))
                children = _ax_attr(elem, "AXChildren") or []
                # reversed keeps document (top-to-bottom) order on the stack
                for child in reversed(list(children)):
                    stack.append((child, depth + 1))

        win_title = str(_ax_attr(windows[0], "AXTitle") or "") if windows else ""
        header = f"현재 앱: {name}"
        if win_title:
            header += f' — 창: "{win_title}"'
        lines = [header]
        for i, (elem, role, title, value) in enumerate(entries, start=1):
            _SNAPSHOT[i] = elem
            line = f'[{i}] {_ROLE_KO.get(role, role)} "{title}"'
            if value:
                line += f' 값="{value}"'
            lines.append(line)
        if len(entries) < _MIN_ELEMENTS_FOR_AX:
            lines.append(
                "주의: 인식된 요소가 거의 없어요 — 이 앱은 접근성 정보를 제공하지 "
                "않는 것 같습니다. screenshot을 찍어 좌표로 클릭하세요."
            )
        return "\n".join(lines)
    except Exception as e:
        return f"error: 화면 요소를 읽지 못했어요 ({type(e).__name__})"


def element_known(element_id: int) -> bool:
    return element_id in _SNAPSHOT


def element_center(element_id: int):
    """Fresh global center of a snapshotted element, re-read at click time so
    a moved window can't cause a misclick. None if the element is gone."""
    elem = _SNAPSHOT.get(element_id)
    if elem is None:
        return None
    return _ax_center(elem)


def _ax_actions(elem) -> list:
    import ApplicationServices as AS
    err, actions = AS.AXUIElementCopyActionNames(elem, None)
    return list(actions or []) if err == 0 else []


def _ax_perform(elem, action) -> bool:
    import ApplicationServices as AS
    return AS.AXUIElementPerformAction(elem, action) == 0


def _ax_settable(elem, name) -> bool:
    import ApplicationServices as AS
    err, settable = AS.AXUIElementIsAttributeSettable(elem, name, None)
    return err == 0 and bool(settable)


def _ax_set(elem, name, value) -> bool:
    import ApplicationServices as AS
    return AS.AXUIElementSetAttributeValue(elem, name, value) == 0


def _running_apps() -> list:
    """[(localized name, pid)] of currently running apps."""
    import AppKit
    return [(str(a.localizedName() or ""), int(a.processIdentifier()))
            for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications()]


# The app the current command works on. Pinned by launch_app or the first
# read_screen of a command, cleared when a new command starts — so the agent
# keeps driving ITS app even when the user focuses something else.
_TARGET_PID: int | None = None
_TARGET_NAME: str | None = None


def set_target_app(name: str) -> bool:
    """Pin the agent's target app by name. Exact localized-name match first,
    then substring, case-insensitive. False when no running app matches."""
    global _TARGET_PID, _TARGET_NAME
    want = name.strip().lower()
    if not want:
        return False
    apps = _running_apps()
    for app_name, pid in apps:
        if app_name.lower() == want:
            _TARGET_PID, _TARGET_NAME = pid, app_name
            return True
    for app_name, pid in apps:
        if want in app_name.lower():
            _TARGET_PID, _TARGET_NAME = pid, app_name
            return True
    return False


def clear_target_app() -> None:
    global _TARGET_PID, _TARGET_NAME
    _TARGET_PID = None
    _TARGET_NAME = None


# Let the freshly-activated app finish its window-ordering before the click
# glide starts; without this the first click can land mid-reorder.
_ACTIVATE_SETTLE_SEC = 0.2


def _activate_pid(pid: int) -> bool:
    import AppKit
    for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
        if int(app.processIdentifier()) == pid:
            app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
            return True
    return False


def activate_target_app() -> bool:
    """Bring the pinned target app to the front. A real mouse click lands on
    the TOPMOST window at that point, so the target must be frontmost or the
    click could hit another app's window. True when the target is (already)
    frontmost or was activated; False when no target is pinned or it is gone."""
    if _TARGET_PID is None:
        return False
    _, pid = _frontmost_app()
    if pid == _TARGET_PID:
        return True
    if not _activate_pid(_TARGET_PID):
        return False
    time.sleep(_ACTIVATE_SETTLE_SEC)
    return True


def press_element(element_id: int, double: bool = False):
    """Actuate a snapshotted element via its AX action — no cursor movement,
    works while the app is in the background. Returns the result string, or
    None when the element exposes no usable action (caller falls back to a
    real mouse click)."""
    elem = _SNAPSHOT.get(element_id)
    if elem is None:
        return None
    names = _ax_actions(elem)
    if double and "AXOpen" in names:
        action = "AXOpen"
    elif "AXPress" in names:
        action = "AXPress"
    else:
        return None
    if not _ax_perform(elem, action):
        return None
    return f"pressed element {element_id} ({action})"


def set_element_value(element_id: int, text: str) -> str:
    """Set a text element's value directly via AX — no keyboard, clipboard,
    or focus involved."""
    elem = _SNAPSHOT.get(element_id)
    if elem is None:
        return (f"error: 알 수 없는 요소 id {element_id} — "
                "read_screen을 먼저 실행하세요")
    if not _ax_settable(elem, "AXValue") or not _ax_set(elem, "AXValue", text):
        return ("error: 이 요소에는 값을 직접 넣을 수 없어요 — "
                "click_element 후 type_text를 쓰세요")
    return f"value set on element {element_id}"
