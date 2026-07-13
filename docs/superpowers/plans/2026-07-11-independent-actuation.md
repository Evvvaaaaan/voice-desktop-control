# Independent Actuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** click_element을 AXPress로, 텍스트필드 입력을 AXSetValue(`set_value`)로 바꾸고 대상 앱을 고정해, VoiceDesk가 사용자 마우스·포커스·클립보드를 건드리지 않고 백그라운드에서 동작하게 한다.

**Architecture:** `actions/accessibility.py`에 AX 액션 수행(press)·값 설정·대상 pid 고정을 추가. `agent/tools.py`의 click_element가 AXPress 우선 + 마우스 폴백으로 바뀌고 `set_value` 액션이 신설된다. `agent/core.py`는 명령 시작 시 대상을 초기화하고 set_value에도 텍스트 관찰을 준다. 프롬프트는 `agent/context.py`만 수정.

**Tech Stack:** Python 3.12, pyobjc(ApplicationServices/AppKit), pytest + pytest-mock (전부 모킹).

**Spec:** `docs/superpowers/specs/2026-07-11-independent-actuation-design.md`

## Global Constraints

- 테스트 전부 모킹, AX 호출은 소형 프라이빗 헬퍼 뒤에 격리해 monkeypatch.
- 프롬프트는 `agent/context.py`에만. 사용자 문자열 한국어, 코드/커밋 영어.
- 마우스 폴백 결과 문자열에는 반드시 `(mouse fallback)` 표기.
- `run_applescript`는 실패 시 `"error: ..."` 반환 (launch_app pin 조건에 사용).
- 기존 window-use·스크린샷 테스트 회귀 금지. 작업 브랜치: `feature/window-use`.

---

### Task 1: AX 액션·값 설정·대상 고정 (`actions/accessibility.py`)

**Files:**
- Modify: `actions/accessibility.py`
- Test: `tests/test_actions.py`

**Interfaces:**
- Produces (Task 2·3 사용):
  - `press_element(element_id: int, double: bool = False) -> str | None` — AX 액션 성공 시 `"pressed element N (AXPress|AXOpen)"`, AX 액션 불가/실패 시 None(호출자가 마우스 폴백)
  - `set_element_value(element_id: int, text: str) -> str` — 성공 `"value set on element N"`, 실패 `"error: ..."`
  - `set_target_app(name: str) -> bool`, `clear_target_app() -> None`
  - `snapshot_screen()` — 대상 고정 반영(고정 없으면 첫 호출이 프론트 앱을 고정)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_actions.py`의 `_patch_ax`를 확장하고 테스트 추가:

`_patch_ax` 함수를 다음으로 교체:

```python
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
```

파일 끝에 추가:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_actions.py -q -k "press_element or set_element_value or pinned or pins_first or target_app_gone"`
Expected: FAIL — `AttributeError`(모듈에 `clear_target_app`/`_running_apps`/`_ax_actions` 없음) 또는 ImportError.

- [ ] **Step 3: 구현** — `actions/accessibility.py`의 `element_center` 아래에 추가:

```python
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
```

`snapshot_screen()`의 대상 결정부를 교체 — 기존:

```python
    name, pid = _frontmost_app()
    if pid is None:
        return "error: 활성 앱을 찾을 수 없어요"
```

를 다음으로:

```python
    global _TARGET_PID, _TARGET_NAME
    name, pid = _TARGET_NAME, _TARGET_PID
    if pid is not None and all(p != pid for _, p in _running_apps()):
        return f"error: 대상 앱({name})이 종료되었어요 — 앱을 다시 실행해 주세요"
    if pid is None:
        name, pid = _frontmost_app()
        if pid is None:
            return "error: 활성 앱을 찾을 수 없어요"
        _TARGET_PID, _TARGET_NAME = pid, name
```

(주의: `global` 선언은 함수 첫 부분, `_SNAPSHOT.clear()` 다음에 둔다.)

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/test_actions.py -q`
Expected: PASS (기존 스냅샷 테스트 포함 — `_patch_ax`가 `clear_target_app()`을 호출하므로 상태 누수 없음)

- [ ] **Step 5: 커밋**

```bash
git add actions/accessibility.py tests/test_actions.py
git commit -m "feat: AX press/set-value and target-app pinning for independent actuation"
```

---

### Task 2: dispatch — AXPress 우선 클릭 + set_value + launch_app pin (`agent/tools.py`)

**Files:**
- Modify: `agent/tools.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: Task 1의 `press_element`, `set_element_value`, `set_target_app`
- Produces: `dispatch("click_element", ...)` — AX 성공 시 `"pressed element N (...)"`, 마우스 폴백 시 기존 문자열 + `" (mouse fallback)"`; `dispatch("set_value", {"id", "text"})`; launch_app 성공 시 대상 고정

- [ ] **Step 1: 기존 폴백 테스트 3건 수정 + 신규 테스트 작성**

`tests/test_agent.py`의 `test_dispatch_click_element_stale_element`에 `press_element` patch를 추가 (미패치 시 이전 테스트가 남긴 모듈 `_SNAPSHOT` 상태에 따라 실제 AX 헬퍼가 가짜 dict에 호출될 수 있음):

```python
def test_dispatch_click_element_stale_element(mocker):
    mocker.patch("actions.accessibility.element_known", return_value=True)
    mocker.patch("actions.accessibility.press_element", return_value=None)
    mocker.patch("actions.accessibility.element_center", return_value=None)
    res = dispatch("click_element", {"id": 3})
    assert res.startswith("error: 요소 3")
```

`test_dispatch_click_element_clicks_fresh_center`와 `test_dispatch_click_element_double`을 다음으로 교체 (press_element가 None을 반환하는 폴백 상황으로 명시):

```python
def test_dispatch_click_element_falls_back_to_mouse(mocker):
    mocker.patch("actions.accessibility.element_known", return_value=True)
    mocker.patch("actions.accessibility.press_element", return_value=None)
    mocker.patch("actions.accessibility.element_center", return_value=(120.0, 240.0))
    mock_click = mocker.patch("agent.tools.click")
    res = dispatch("click_element", {"id": 2})
    mock_click.assert_called_once_with(120, 240)
    assert res == "clicked element 2 at 120,240 (mouse fallback)"


def test_dispatch_click_element_double_falls_back_to_mouse(mocker):
    mocker.patch("actions.accessibility.element_known", return_value=True)
    mocker.patch("actions.accessibility.press_element", return_value=None)
    mocker.patch("actions.accessibility.element_center", return_value=(10.0, 20.0))
    mock_double = mocker.patch("agent.tools.double_click")
    res = dispatch("click_element", {"id": 1, "double": True})
    mock_double.assert_called_once_with(10, 20)
    assert res == "double_clicked element 1 at 10,20 (mouse fallback)"
```

파일 끝에 추가:

```python
# ---------- independent actuation dispatch ----------

def test_dispatch_click_element_prefers_ax_press(mocker):
    mocker.patch("actions.accessibility.element_known", return_value=True)
    mocker.patch("actions.accessibility.press_element",
                 return_value="pressed element 2 (AXPress)")
    mock_click = mocker.patch("agent.tools.click")
    res = dispatch("click_element", {"id": 2})
    assert res == "pressed element 2 (AXPress)"
    mock_click.assert_not_called()


def test_dispatch_set_value(mocker):
    mock_set = mocker.patch("actions.accessibility.set_element_value",
                            return_value="value set on element 3")
    res = dispatch("set_value", {"id": 3, "text": "안녕"})
    mock_set.assert_called_once_with(3, "안녕")
    assert res == "value set on element 3"


def test_dispatch_set_value_requires_id_and_text(mocker):
    assert dispatch("set_value", {"text": "x"}).startswith("error: set_value")
    assert dispatch("set_value", {"id": 1}).startswith("error: set_value")


def test_dispatch_set_value_long_text_uses_confirm_gate(mocker):
    from agent import tools
    mock_set = mocker.patch("actions.accessibility.set_element_value",
                            return_value="value set on element 1")
    tools.set_text_input_provider(lambda prompt, draft: "수정된 텍스트입니다 열자넘음")
    try:
        res = dispatch("set_value", {"id": 1, "text": "가나다라마바사아자차카"})
    finally:
        tools.set_text_input_provider(None)
    mock_set.assert_called_once_with(1, "수정된 텍스트입니다 열자넘음")
    assert res == "value set on element 1"


def test_dispatch_launch_app_pins_target(mocker):
    mocker.patch("agent.tools.run_applescript", return_value="")
    mock_pin = mocker.patch("actions.accessibility.set_target_app")
    dispatch("launch_app", {"app": "Safari"})
    mock_pin.assert_called_once_with("Safari")


def test_dispatch_launch_app_does_not_pin_on_error(mocker):
    mocker.patch("agent.tools.run_applescript", return_value="error: no such app")
    mock_pin = mocker.patch("actions.accessibility.set_target_app")
    dispatch("launch_app", {"app": "NopeApp"})
    mock_pin.assert_not_called()
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_agent.py -q -k "falls_back_to_mouse or prefers_ax_press or set_value or pins_target or pin_on_error"`
Expected: FAIL — 폴백 테스트는 `(mouse fallback)` 미포함, set_value는 `unknown_action:set_value`, pin 테스트는 `set_target_app` 미호출.

- [ ] **Step 3: 구현** — `agent/tools.py`:

launch_app 분기 교체 — 기존:

```python
        return run_applescript(f'tell application "{app}" to activate')
```

를:

```python
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
```

click_element 분기에서 `element_known` 검사와 `center = ...` 사이에 삽입:

```python
        pressed = accessibility.press_element(element_id, bool(params.get("double")))
        if pressed is not None:
            return pressed
        # No usable AX action — real mouse click is the one element path
        # that still interferes with the user's pointer.
```

그리고 두 return 문자열에 `" (mouse fallback)"`을 덧붙인다:

```python
            return f"double_clicked element {element_id} at {x},{y} (mouse fallback)"
        click(x, y)
        return f"clicked element {element_id} at {x},{y} (mouse fallback)"
```

`click_element` 분기 다음에 `set_value` 분기 추가:

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/test_agent.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add agent/tools.py tests/test_agent.py
git commit -m "feat: AXPress-first click, set_value action, launch_app target pinning"
```

---

### Task 3: 루프 통합 — 대상 초기화, set_value 관찰·캐시 (`agent/core.py`)

**Files:**
- Modify: `agent/core.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: Task 1의 `clear_target_app`
- Produces: `run()` 시작마다 대상 해제; `set_value`도 텍스트 관찰 + 캐시 제외

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_agent.py` 끝에 추가:

```python
def test_run_clears_target_app_each_command(mocker):
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.return_value = (
        '{"action":"speak_only","params":{},"done":true,"response":"네"}'
    )
    agent = _mk_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="")
    mocker.patch("agent.core.speak")
    mock_clear = mocker.patch("agent.core.clear_target_app")
    agent.run("안녕")
    mock_clear.assert_called_once()


def test_set_value_observation_is_text_with_fresh_elements(mocker):
    mock_llm = MagicMock()
    mock_llm.supports_vision = True
    mock_llm.complete.side_effect = [
        '{"action":"set_value","params":{"id":2,"text":"hi"},"done":false,"response":"입력"}',
        '{"action":"speak_only","params":{},"done":true,"response":"완료"}',
    ]
    agent = _mk_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="value set on element 2")
    mocker.patch("agent.core.run_applescript", return_value="TestApp")
    mocker.patch("agent.core.snapshot_screen", return_value='[1] 버튼 "확인"')
    mocker.patch("agent.core.time.sleep")
    mocker.patch("agent.core.speak")

    agent.run("주소창에 입력해줘")

    messages = mock_llm.complete.call_args_list[1][0][0]
    obs_msgs = [m for m in messages
                if m["role"] == "user" and "관찰" in str(m.get("content", ""))]
    assert obs_msgs, "no observation message found"
    assert '버튼 "확인"' in obs_msgs[-1]["content"]
    mock_llm.build_observation.assert_not_called()


def test_set_value_is_never_hot_cached(mocker):
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.return_value = (
        '{"action":"set_value","params":{"id":1,"text":"x"},"done":true,"response":"입력했어요"}'
    )
    agent = _mk_agent(mock_llm)
    mocker.patch("agent.core.tools.dispatch", return_value="value set on element 1")
    mocker.patch("agent.core.speak")
    record = mocker.patch.object(agent._cache, "record")
    agent.run("입력해줘")
    record.assert_not_called()
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_agent.py -q -k "clears_target or set_value_observation or set_value_is_never"`
Expected: 3 FAIL — `agent.core`에 `clear_target_app` 없음(AttributeError), 관찰에 요소 목록 없음, `record` 호출됨.

- [ ] **Step 3: 구현** — `agent/core.py`:

import 수정:

```python
from actions.accessibility import snapshot_screen, clear_target_app
```

`_UNCACHEABLE_ACTIONS`에 `"set_value"` 추가:

```python
_UNCACHEABLE_ACTIONS = {"speak_only", "read_screen", "click_element", "set_value"}
```

`_observe`의 window-use 분기를 set_value 포함으로 교체:

```python
        if action in ("read_screen", "click_element", "set_value"):
            # Window-use observations are text: read_screen's listing is
            # already in dispatch_res, and after a click/set we re-read the
            # elements so the model verifies the result without a screenshot.
            if action != "read_screen" and not dispatch_res.startswith("error"):
                time.sleep(_ELEMENT_SETTLE_SEC)
                text += "\n현재 화면 요소:\n" + snapshot_screen()
            return {"role": "user", "content": text}
```

`run()`에서 `cached = self._cache.get(command)` 바로 앞에 추가:

```python
        try:
            clear_target_app()
        except Exception:
            pass
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/test_agent.py -q`
Expected: PASS (기존 done-gate·거짓 성공 테스트 회귀 없음 포함)

- [ ] **Step 5: 커밋**

```bash
git add agent/core.py tests/test_agent.py
git commit -m "feat: per-command target reset and set_value loop integration"
```

---

### Task 4: 프롬프트 개정 + 전체 검증 (`agent/context.py`, CLAUDE.md)

**Files:**
- Modify: `agent/context.py`, `CLAUDE.md`
- Test: `tests/test_agent.py`

- [ ] **Step 1: 프롬프트 테스트 확장** — `test_system_prompt_documents_window_use`에 한 줄 추가:

```python
    assert "set_value" in SYSTEM_PROMPT
```

Run: `python3 -m pytest tests/test_agent.py::test_system_prompt_documents_window_use -v`
Expected: FAIL

- [ ] **Step 2: SYSTEM_PROMPT 수정** — `agent/context.py`:

액션 목록에서 click_element 줄을 다음으로 교체하고 set_value 줄 추가:

```
- click_element    params: {"id": <int>}                   — press element [id] via Accessibility (NO mouse movement; add "double": true to open/double-click)
- set_value        params: {"id": <int>, "text": "<text>"} — put text into field [id] directly (no keyboard/clipboard; PREFERRED over type_text for fields)
```

규칙 6 끝에 다음 문장 추가:

```
   The agent works on a TARGET app — the app opened by launch_app or the
   app of the first read_screen — and keeps driving it even if the user
   focuses another window. click_element presses via Accessibility (the
   user's mouse never moves); to type into a field, prefer set_value with
   the field's id. type_text/press_key act on the FOCUSED app and may
   interfere with the user — use them only when set_value fails.
```

- [ ] **Step 3: CLAUDE.md 캐시 규칙 갱신** — 기존 `(read_screen/click_element)` 를 `(read_screen/click_element/set_value)` 로 교체.

- [ ] **Step 4: 전체 스위트**

Run: `python3 -m pytest tests/ -q`
Expected: 전부 통과. 플레이크 2건 발생 시 단독 재실행으로 확인.

- [ ] **Step 5: 커밋**

```bash
git add agent/context.py CLAUDE.md tests/test_agent.py
git commit -m "feat: document independent actuation in system prompt"
```
