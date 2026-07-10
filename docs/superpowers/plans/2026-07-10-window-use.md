# Window Use (AX 기반 화면 제어) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM 에이전트가 macOS 접근성(AX) 트리를 읽어(`read_screen`) 요소 번호로 클릭(`click_element`)하게 하고, 기존 스크린샷+그리드 경로는 폴백으로 유지한다.

**Architecture:** `actions/accessibility.py`에 AX 스냅샷 워커(id→요소 참조 저장)를 추가하고, `agent/tools.py` dispatch에 두 액션을 연결한다. `agent/core.py`는 요소 액션 후 관찰을 스크린샷 대신 신선한 요소 목록 텍스트로 구성하고, 스냅샷 의존 액션을 핫 캐시에서 제외한다. 시스템 프롬프트는 `agent/context.py`에서만 수정한다.

**Tech Stack:** Python 3.12, pyobjc(ApplicationServices/AppKit — 이미 의존성에 있음), pytest + pytest-mock (전부 모킹, 네트워크/실제 화면 접근 금지).

**Spec:** `docs/superpowers/specs/2026-07-10-window-use-design.md`

## Global Constraints

- 테스트는 전부 모킹 — 실제 AX/마우스/화면 접근 금지 (프로젝트 규약).
- 시스템 프롬프트는 `agent/context.py`에만 존재 — `llm/*`에 프롬프트 추가 금지.
- 사용자 대상 문자열(오류 메시지 포함)은 한국어, 코드/주석/커밋 메시지는 영어.
- 하드 캡: 방문 6,000 노드 / 깊이 25 / 목록 150개 / 창 2개 / 제목 40자 절단.
- AX 메시징 타임아웃 0.3s, Chromium 플래그 설정 후 0.3s 대기, 클릭 후 관찰 전 0.4s 안정화.
- 요소 부족 판정 기준: 인터랙티브 요소 5개 미만.
- 기존 스크린샷/좌표 경로는 수정하지 않는다 (회귀 금지).
- 전체 스위트를 변경 **전후로** 실행. 알려진 순서 의존 플레이크: `test_stt.py::test_whisper_local_adapter`, `test_llm.py::test_claude_supports_vision_and_builds_image_observation` — 단독 재실행으로 확인.

---

### Task 1: AX 스냅샷 워커 (`actions/accessibility.py`)

**Files:**
- Modify: `actions/accessibility.py` (기존 `click_element_by_name`은 그대로 둠)
- Test: `tests/test_actions.py` (파일 끝에 추가)

**Interfaces:**
- Produces (Task 2·3이 사용):
  - `snapshot_screen() -> str` — 요소 목록 텍스트 또는 `"error: ..."` 문자열. 호출할 때마다 스냅샷 세대 교체(이전 id 전부 무효).
  - `element_known(element_id: int) -> bool` — 최신 스냅샷에 id가 있는지.
  - `element_center(element_id: int) -> tuple[float, float] | None` — 클릭 시점의 신선한 전역 중심 좌표. 요소가 사라졌으면 None.

- [ ] **Step 0: 베이스라인 — 변경 전 전체 스위트 실행**

Run: `python3 -m pytest tests/ -q`
Expected: 전부 통과 (플레이크 2건이 실패하면 단독 재실행으로 통과 확인 후 기록).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_actions.py` 끝에 추가:

```python
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
    monkeypatch.setattr(ax, "_ax_trusted", lambda: trusted)
    monkeypatch.setattr(ax, "_frontmost_app", lambda: (app_name, 123))
    monkeypatch.setattr(ax, "_ax_app", lambda pid: {"AXWindows": [window]})
    monkeypatch.setattr(ax, "_ax_attr", lambda elem, name: elem.get(name))
    monkeypatch.setattr(ax, "_ax_center", lambda elem: elem.get("center"))


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
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_actions.py -q -k "snapshot or element_center"`
Expected: FAIL — `ImportError: cannot import name 'snapshot_screen'`

- [ ] **Step 3: 구현**

`actions/accessibility.py` — 파일 상단 import에 `time` 추가, 기존 `click_element_by_name` 아래에 추가:

```python
import subprocess
import time
```

```python
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
    _SNAPSHOT.clear()
    if not _ax_trusted():
        return ("error: 접근성 권한이 없어요 — 시스템 설정 → 개인정보 보호 및 보안 → "
                "손쉬운 사용에서 VoiceDesk를 허용해 주세요")
    name, pid = _frontmost_app()
    if pid is None:
        return "error: 활성 앱을 찾을 수 없어요"
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
```

주의: pyobjc import는 전부 헬퍼 함수 안(lazy) — 테스트는 헬퍼를 monkeypatch하므로 실제 AX를 절대 건드리지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/test_actions.py -q`
Expected: PASS (기존 test_actions 테스트 포함 전부)

- [ ] **Step 5: 커밋**

```bash
git add actions/accessibility.py tests/test_actions.py
git commit -m "feat: add AX tree snapshot walker for window use"
```

---

### Task 2: dispatch 연결 (`agent/tools.py`)

**Files:**
- Modify: `agent/tools.py`
- Test: `tests/test_agent.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: Task 1의 `snapshot_screen()`, `element_known(id)`, `element_center(id)`
- Produces: `dispatch("read_screen", {})` / `dispatch("click_element", {"id": N, "double": bool})` — 성공 시 `"clicked element N at x,y"`, 실패 시 `"error: ..."` (기존 done-gate가 오류 문자열로 거짓 완료를 차단)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent.py` 끝에 추가:

```python
# ---------- window-use dispatch ----------

def test_dispatch_read_screen_returns_listing(mocker):
    mocker.patch(
        "actions.accessibility.snapshot_screen",
        return_value='현재 앱: TestApp\n[1] 버튼 "확인"',
    )
    res = dispatch("read_screen", {})
    assert res.startswith("현재 앱: TestApp")
    assert '[1] 버튼 "확인"' in res


def test_dispatch_click_element_clicks_fresh_center(mocker):
    mocker.patch("actions.accessibility.element_known", return_value=True)
    mocker.patch("actions.accessibility.element_center", return_value=(120.0, 240.0))
    mock_click = mocker.patch("agent.tools.click")
    res = dispatch("click_element", {"id": 2})
    mock_click.assert_called_once_with(120, 240)
    assert res == "clicked element 2 at 120,240"


def test_dispatch_click_element_double(mocker):
    mocker.patch("actions.accessibility.element_known", return_value=True)
    mocker.patch("actions.accessibility.element_center", return_value=(10.0, 20.0))
    mock_double = mocker.patch("agent.tools.double_click")
    res = dispatch("click_element", {"id": 1, "double": True})
    mock_double.assert_called_once_with(10, 20)
    assert res == "double_clicked element 1 at 10,20"


def test_dispatch_click_element_unknown_id(mocker):
    mocker.patch("actions.accessibility.element_known", return_value=False)
    res = dispatch("click_element", {"id": 99})
    assert res.startswith("error: 알 수 없는 요소 id 99")


def test_dispatch_click_element_stale_element(mocker):
    mocker.patch("actions.accessibility.element_known", return_value=True)
    mocker.patch("actions.accessibility.element_center", return_value=None)
    res = dispatch("click_element", {"id": 3})
    assert res.startswith("error: 요소 3")


def test_dispatch_click_element_requires_int_id():
    res = dispatch("click_element", {"id": "abc"})
    assert res.startswith("error: click_element")
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_agent.py -q -k "dispatch_read_screen or dispatch_click_element"`
Expected: FAIL — `unknown_action:read_screen` / `unknown_action:click_element` (assert 실패)

- [ ] **Step 3: 구현**

`agent/tools.py` — import에 추가:

```python
from actions import accessibility
```

`elif action == "screenshot":` 분기 **앞**에 추가:

```python
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
```

(모듈 참조 `accessibility.snapshot_screen()` 형태 유지 — 테스트가 `actions.accessibility.*`를 patch하면 dispatch가 그것을 본다.)

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/test_agent.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add agent/tools.py tests/test_agent.py
git commit -m "feat: wire read_screen and click_element into action dispatch"
```

---

### Task 3: 에이전트 루프 통합 — 텍스트 관찰 + 캐시 제외 (`agent/core.py`)

**Files:**
- Modify: `agent/core.py`
- Test: `tests/test_agent.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: Task 1의 `snapshot_screen()` (관찰용 재스냅샷), Task 2의 dispatch 결과 문자열
- Produces: `click_element` 성공 후 관찰 = 텍스트 + 신선한 요소 목록 (스크린샷/`build_observation` 호출 없음); `read_screen`·`click_element`는 핫 캐시 기록 제외

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent.py` 끝에 추가:

```python
# ---------- window-use agent loop integration ----------

def _mk_agent(mock_llm):
    guard = MagicMock()
    guard.check.return_value = True
    guard.is_dangerous.return_value = False
    detector = MagicMock()
    detector.record.return_value = False
    return Agent(mock_llm, guard, MagicMock(), detector,
                 MagicMock(voice="Yuna", rate=200))


def test_click_element_observation_is_text_with_fresh_elements(mocker):
    mock_llm = MagicMock()
    mock_llm.supports_vision = True   # vision model still gets TEXT here
    mock_llm.complete.side_effect = [
        '{"action":"click_element","params":{"id":3},"done":false,"response":"클릭"}',
        '{"action":"speak_only","params":{},"done":true,"response":"완료"}',
    ]
    agent = _mk_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch",
                 return_value="clicked element 3 at 100,200")
    mocker.patch("agent.core.run_applescript", return_value="TestApp")
    mocker.patch("agent.core.snapshot_screen", return_value='[1] 버튼 "확인"')
    mocker.patch("agent.core.time.sleep")
    mocker.patch("agent.core.speak")

    agent.run("확인 눌러줘")

    second_call_messages = mock_llm.complete.call_args_list[1][0][0]
    obs = second_call_messages[-1]
    assert obs["role"] == "user"
    assert '버튼 "확인"' in obs["content"]
    mock_llm.build_observation.assert_not_called()


def test_read_screen_observation_is_text_only(mocker):
    mock_llm = MagicMock()
    mock_llm.supports_vision = True
    listing = '현재 앱: TestApp\n[1] 버튼 "확인"'
    mock_llm.complete.side_effect = [
        '{"action":"read_screen","params":{},"done":false,"response":"확인 중"}',
        '{"action":"speak_only","params":{},"done":true,"response":"완료"}',
    ]
    agent = _mk_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value=listing)
    mocker.patch("agent.core.run_applescript", return_value="TestApp")
    mocker.patch("agent.core.speak")

    agent.run("화면 읽어줘")

    second_call_messages = mock_llm.complete.call_args_list[1][0][0]
    obs = second_call_messages[-1]
    assert '[1] 버튼 "확인"' in obs["content"]
    mock_llm.build_observation.assert_not_called()


def test_click_element_is_never_hot_cached(mocker):
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.return_value = (
        '{"action":"click_element","params":{"id":1},"done":true,"response":"눌렀어요"}'
    )
    agent = _mk_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch",
                 return_value="clicked element 1 at 5,5")
    mocker.patch("agent.core.speak")
    record = mocker.patch.object(agent._cache, "record")

    agent.run("확인 눌러줘")

    record.assert_not_called()
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_agent.py -q -k "observation_is_text or never_hot_cached"`
Expected: 2 FAIL, 1 PASS —
- `test_click_element_observation_...` FAIL: 관찰 content에 신선한 요소 목록('버튼 "확인"')이 없음
- `test_click_element_is_never_hot_cached` FAIL: `record`가 호출됨
- `test_read_screen_observation_is_text_only`는 기존 코드에서도 통과(회귀 가드) — read_screen이 `_SCREEN_OBSERVATION_ACTIONS`에 없어 이미 텍스트 관찰이기 때문. 실패 사유가 위와 같은지 출력을 읽고 확인할 것.

- [ ] **Step 3: 구현**

`agent/core.py` 수정 4곳:

(1) import 추가 — 기존 `from actions.screen import take_screenshot_with_grid` 아래:

```python
from actions.accessibility import snapshot_screen
```

(2) 모듈 상수 — `_SCREEN_OBSERVATION_ACTIONS` 정의 아래에 추가:

```python
# Snapshot-dependent actions can't be replayed from the hot cache (the id
# refers to a screen that no longer exists), and read_screen alone does
# nothing user-visible.
_UNCACHEABLE_ACTIONS = {"speak_only", "read_screen", "click_element"}

# Let the UI react (menu open, page transition) before re-reading elements.
_ELEMENT_SETTLE_SEC = 0.4
```

(3) `_observe` — `text = (...)` 대입 **직후**, vision 분기 **앞**에 추가:

```python
        if action in ("read_screen", "click_element"):
            # Window-use observations are text: read_screen's listing is
            # already in dispatch_res, and after a click we re-read the
            # elements so the model verifies the result without a screenshot.
            if action == "click_element" and not dispatch_res.startswith("error"):
                time.sleep(_ELEMENT_SETTLE_SEC)
                text += "\n클릭 후 화면 요소:\n" + snapshot_screen()
            return {"role": "user", "content": text}
```

(4) 캐시 기록 조건 — `if i == 0 and action != "speak_only":` 를 다음으로 교체:

```python
                    if i == 0 and action not in _UNCACHEABLE_ACTIONS:
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/test_agent.py -q`
Expected: PASS — 특히 기존 `test_done_rejected_when_final_action_fails_then_recovers`, `test_false_success_claim_never_spoken_when_action_keeps_failing` 회귀 없음 확인.

- [ ] **Step 5: 커밋**

```bash
git add agent/core.py tests/test_agent.py
git commit -m "feat: text-based element observations and cache exclusion for window use"
```

---

### Task 4: 시스템 프롬프트 개정 (`agent/context.py`)

**Files:**
- Modify: `agent/context.py` (SYSTEM_PROMPT 문자열 전체 교체)
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: Task 2의 액션 이름/파라미터 규약 (`read_screen`, `click_element {"id", "double"}`)
- Produces: 모델이 window use를 기본 경로로, 스크린샷+그리드를 폴백으로 쓰도록 하는 규칙

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent.py` 끝에 추가:

```python
def test_system_prompt_documents_window_use():
    from agent.context import SYSTEM_PROMPT
    assert "read_screen" in SYSTEM_PROMPT
    assert "click_element" in SYSTEM_PROMPT
    # screenshot flow must remain documented as the fallback
    assert "screenshot" in SYSTEM_PROMPT
    assert "0-1000" in SYSTEM_PROMPT or "0–1000" in SYSTEM_PROMPT
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_agent.py::test_system_prompt_documents_window_use -v`
Expected: FAIL — `"read_screen" in SYSTEM_PROMPT` assert 실패

- [ ] **Step 3: SYSTEM_PROMPT 전체 교체**

`agent/context.py`의 `SYSTEM_PROMPT = """..."""` 를 아래로 통째로 교체:

```python
SYSTEM_PROMPT = """You are VoiceDesk, a macOS desktop assistant controlled by voice.
You act as a ReAct agent: take ONE action, observe the result, then keep going
until the user's ENTIRE request is complete.

Respond with ONLY a single JSON object — no prose, no markdown fences:
{"action": "<tool>", "params": {...}, "done": <true|false>, "response": "<Korean text spoken to the user>"}

Available actions:
- launch_app       params: {"app": "<application name>"}   — open/activate a macOS app
- open_url         params: {"url": "https://..."}          — open a web page in the default browser
- read_screen      params: {}                              — list the front app's clickable UI elements as numbered [id] lines (fast, PREFERRED for screen control)
- click_element    params: {"id": <int>}                   — click element [id] from the LAST read_screen; add "double": true to double-click
- screenshot       params: {}                              — capture the screen so you can SEE it (fallback when read_screen finds nothing)
- click            params: {"x": <0-1000>, "y": <0-1000>}  — move the real mouse there and click (fallback)
- double_click     params: {"x": <0-1000>, "y": <0-1000>}
- move_mouse       params: {"x": <0-1000>, "y": <0-1000>}  — move the pointer without clicking
- type_text        params: {"text": "<text>"}
- press_key        params: {"key": "<key>"}                — e.g. "enter", "cmd+t"
- scroll           params: {"direction": "up|down", "amount": <int>}
- run_applescript  params: {"script": "<AppleScript>"}
- run_routine      params: {"name": "<routine name>"}
- speak_only       params: {}                              — just talk, no action (set done=true)

Rules:
1. A command may need MULTIPLE steps. Set "done": false and continue until every
   part is finished. Only set "done": true on the final step.
2. To search the web or open a site, prefer open_url. To search Google use
   {"action":"open_url","params":{"url":"https://www.google.com/search?q=<query>"}}.
3. After each non-final step you receive an observation of the current state —
   use it to decide the next step.
4. "response" is spoken aloud in Korean; keep it short.
5. The user's command comes from SPEECH RECOGNITION and may contain
   mis-transcriptions. Interpret phonetically similar Korean/English words as
   the intended app or action (e.g. "크름"/"그롬" → 크롬/Google Chrome,
   "그럼 열고 ..." → "크롬 열고 ...", "사파레" → Safari,
   "지메일"/"쥐메일" → Gmail) instead of failing.
6. CONTROLLING THE SCREEN (window use): to click a button, link, field,
   menu item, or any on-screen element that has no direct command, FIRST
   run read_screen (done=false). It lists the front app's clickable
   elements as numbered lines like [3] 버튼 "확인" — then use click_element
   with that id. This is faster and far more accurate than clicking by
   screen coordinates. Element ids are ONLY valid for the LATEST
   read_screen: after a click that changes the screen (menu opened, page
   changed), use the fresh element list included in the observation, or
   run read_screen again. Never reuse an id from an older listing.
7. SCREENSHOT FALLBACK (computer use): if read_screen returns an error or
   says the app exposes almost no elements (games, canvas-drawn UIs), use
   the screenshot flow instead: take a "screenshot" action (done=false),
   then click/double_click/move_mouse by coordinates. Coordinates are a
   resolution-independent grid: x and y each run 0–1000, with (0,0) at the
   TOP-LEFT and (1000,1000) at the BOTTOM-RIGHT of the screen. Every
   screenshot has a GREEN GRID burned into it with axis labels every 100
   units (0, 100, 200, ... 900 along the top and left edges) — READ the
   target's position off this grid instead of estimating; find the two
   nearest gridlines around the element and interpolate between their
   labels.
8. PRECISION CLICKING (screenshot fallback only): small or closely-packed
   targets (icons, tabs, X close buttons) are easy to misjudge by grid
   alone. For anything you're not confident about, do move_mouse first
   (done=false) — the next screenshot shows the ACTUAL cursor position,
   which you can compare against the target and the grid to correct your
   (x,y) before the real click. Skip this extra step only for large,
   unambiguous targets. After every click, verify in the next observation
   that it landed (menu opened, field focused, page changed) before moving
   on; if it clearly didn't work, retry with corrected coordinates rather
   than repeating the same click blindly.
9. Prefer launch_app / open_url for opening apps and web pages; use
   read_screen + click_element for interacting WITHIN an app (clicking
   page elements, buttons, menus).
10. VERIFY BEFORE done=true — an action is not done because you issued it;
   it is done when the observation proves it. NEVER say "했어요/완료" for
   something that did not actually happen. If an observation reports an
   error, either retry with a corrected step (done=false) or give up
   honestly: {"action":"speak_only","params":{},"done":true,
   "response":"<what failed and why, in Korean>"}. The runtime REJECTS
   done=true when the final action returned an error — you will receive the
   error observation instead, so do not repeat the same failing action
   blindly.

Example — user: "크롬 열고 gmail 검색해줘"
  step 1 -> {"action":"launch_app","params":{"app":"Google Chrome"},"done":false,"response":"크롬을 열고 있어요."}
  step 2 -> {"action":"open_url","params":{"url":"https://www.google.com/search?q=gmail"},"done":true,"response":"크롬에서 gmail을 검색했어요."}

Example — user: "확인 버튼 눌러줘"
  step 1 -> {"action":"read_screen","params":{},"done":false,"response":"화면을 확인하고 있어요."}
  step 2 (observation shows [3] 버튼 "확인") -> {"action":"click_element","params":{"id":3},"done":true,"response":"확인 버튼을 눌렀어요."}

Max 8 steps."""
```

변경 요약: 액션 2줄 추가, 규칙 6(window use 기본 경로) 신설, 기존 그리드 규칙은 7(폴백)로 강등, 기존 7·8·9는 8·9·10으로 재번호(9는 click → read_screen+click_element로 문구 수정), window-use 예시 1개 추가. 나머지 문구는 기존 그대로.

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/test_agent.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add agent/context.py tests/test_agent.py
git commit -m "feat: make window use the primary screen-control path in system prompt"
```

---

### Task 5: 전체 검증 + 문서 한 줄

**Files:**
- Modify: `CLAUDE.md` (Runtime harness rules의 Cache safety 한 줄)

- [ ] **Step 1: CLAUDE.md 캐시 규칙 한 줄 갱신**

`CLAUDE.md`(voicedesk)의:

```
- **Cache safety**: only single-step, non-error, non-speak_only actions may be
  cached (replay safety).
```

를 다음으로 교체:

```
- **Cache safety**: only single-step, non-error actions may be cached (replay
  safety); speak_only and snapshot-dependent window-use actions
  (read_screen/click_element) are excluded.
```

- [ ] **Step 2: 전체 스위트 실행**

Run: `python3 -m pytest tests/ -q`
Expected: 전부 통과. 알려진 플레이크 2건(`test_whisper_local_adapter`, `test_claude_supports_vision_and_builds_image_observation`)이 실패하면 단독 재실행:
`python3 -m pytest tests/test_stt.py::test_whisper_local_adapter tests/test_llm.py::test_claude_supports_vision_and_builds_image_observation -v`

- [ ] **Step 3: 실기기 스모크 확인 절차 기록 (실행은 사용자)**

자동화 불가(마이크/화면 권한 필요). TODO.md에 추가하지 말고 최종 보고에 아래를 안내:
- `python3 scratch/probe_ax.py`로 실제 AX 트리가 잡히는지 (권한 필요)
- `python3 main.py` 후 "확인 버튼 눌러줘"류 명령이 read_screen 경로로 도는지 stderr 로그 확인

- [ ] **Step 4: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: note window-use actions in cache safety rule"
```
