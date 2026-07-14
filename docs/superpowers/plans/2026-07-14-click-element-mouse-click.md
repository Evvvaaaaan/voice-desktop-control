# click_element 마우스 클릭 전환 + 화면 조작 표시 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `click_element`를 AXPress에서 항상 실제 마우스 클릭으로 전환하고, 조작 중 화면 테두리 + 커서 링 표시를 추가한다.

**Architecture:** Python 쪽은 `agent/tools.py` dispatch의 click_element 분기를 마우스 클릭 경로로 단순화하고, 기존 `set_text_input_provider` 패턴의 훅으로 HUD에 "조작 중" 신호를 보낸다. Swift HUD 헬퍼에 `control` JSON 메시지를 추가해 테두리/커서 링 오버레이 창을 관리한다. 끄는 시점은 `NotchHUD.set_state`가 executing 이탈 시 자동 처리한다.

**Tech Stack:** Python 3.12+ (pyobjc, pyautogui, pytest+pytest-mock), Swift(AppKit/SwiftUI, 단일 파일 자동 컴파일).

**Spec:** `docs/superpowers/specs/2026-07-14-click-element-mouse-click-design.md`

## Global Constraints

- 사용자 노출 문자열(에러 메시지 등)은 한국어, 코드·주석은 영어, 커밋 메시지는 한국어 (프로젝트 CLAUDE.md).
- 테스트는 전부 모킹 — 실제 마우스/화면/AX 접근 금지. 실행: `python3 -m pytest tests/ -q` (작업 디렉터리 `/Users/evan/voicedesk`).
- 베이스라인: 2026-07-14 기준 508 passed. 알려진 순서 의존 플레이크: `test_stt.py::test_whisper_local_adapter`, `test_llm.py::test_claude_supports_vision_and_builds_image_observation` — 실패 시 단독 재실행으로 확인.
- 작업 트리에 이 계획과 무관한 사용자 변경분이 있다 (`config.yaml`, `setup.py`, `tests/test_main.py`, `ui/menubar.py`, `assets/`). **절대 `git add -A`/`git add .` 금지** — 각 커밋은 해당 태스크가 만진 파일만 명시적으로 add.
- 시스템 프롬프트는 `agent/context.py`에만 존재. `llm/*`에 프롬프트 추가 금지.
- 커밋 트레일러: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: `activate_target_app()` — 대상 앱 전면화

**Files:**
- Modify: `actions/accessibility.py` (`clear_target_app` 함수 뒤, `press_element` 앞에 추가)
- Test: `tests/test_actions.py` (target-app 테스트들 뒤에 추가)

**Interfaces:**
- Consumes: 기존 모듈 상태 `_TARGET_PID`, 기존 헬퍼 `_frontmost_app()`.
- Produces: `activate_target_app() -> bool` — 대상 앱이 전면이 되면(이미 전면 포함) True, 대상 미지정/소멸이면 False. Task 2의 dispatch가 호출한다. 내부 헬퍼 `_activate_pid(pid: int) -> bool`은 테스트에서 monkeypatch 대상.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_actions.py`의 `test_snapshot_errors_when_target_app_gone` 뒤에 추가:

```python
def test_activate_target_app_false_without_target(monkeypatch):
    from actions import accessibility as ax
    monkeypatch.setattr(ax, "_TARGET_PID", None)
    called = []
    monkeypatch.setattr(ax, "_activate_pid", lambda pid: called.append(pid) or True)
    assert ax.activate_target_app() is False
    assert called == []


def test_activate_target_app_skips_when_already_front(monkeypatch):
    from actions import accessibility as ax
    monkeypatch.setattr(ax, "_TARGET_PID", 123)
    monkeypatch.setattr(ax, "_frontmost_app", lambda: ("TestApp", 123))
    called = []
    monkeypatch.setattr(ax, "_activate_pid", lambda pid: called.append(pid) or True)
    assert ax.activate_target_app() is True
    assert called == []


def test_activate_target_app_activates_background_target(monkeypatch):
    from actions import accessibility as ax
    monkeypatch.setattr(ax, "_TARGET_PID", 123)
    monkeypatch.setattr(ax, "_ACTIVATE_SETTLE_SEC", 0)
    monkeypatch.setattr(ax, "_frontmost_app", lambda: ("OtherApp", 999))
    called = []
    monkeypatch.setattr(ax, "_activate_pid", lambda pid: called.append(pid) or True)
    assert ax.activate_target_app() is True
    assert called == [123]


def test_activate_target_app_false_when_target_gone(monkeypatch):
    from actions import accessibility as ax
    monkeypatch.setattr(ax, "_TARGET_PID", 123)
    monkeypatch.setattr(ax, "_frontmost_app", lambda: ("OtherApp", 999))
    monkeypatch.setattr(ax, "_activate_pid", lambda pid: False)
    assert ax.activate_target_app() is False
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_actions.py -q -k activate_target_app`
Expected: 4 FAILED — `AttributeError: ... has no attribute '_activate_pid'` 또는 `activate_target_app`

- [ ] **Step 3: 구현** — `actions/accessibility.py`, `clear_target_app()` 정의 뒤에 추가:

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/test_actions.py -q -k activate_target_app`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add actions/accessibility.py tests/test_actions.py
git commit -m "click_element 마우스 클릭 전환 대비 대상 앱 전면화 헬퍼 추가

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: click_element — 항상 마우스 클릭 (AXPress 제거)

**Files:**
- Modify: `agent/tools.py:165-187` (click_element 분기)
- Modify: `actions/accessibility.py` (`press_element` 함수 삭제, `_ax_actions`/`_ax_perform` 헬퍼도 함께 삭제 — press_element만 쓰던 헬퍼)
- Test: `tests/test_agent.py:1146-1183` (click_element dispatch 테스트 재작성), `tests/test_agent.py` `test_dispatch_click_element_prefers_ax_press` (~1276행) 삭제, `tests/test_actions.py:504-538` (press_element 테스트 4개 삭제)

**Interfaces:**
- Consumes: Task 1의 `accessibility.activate_target_app()`, 기존 `accessibility.element_known/element_center`, `actions.mouse_keyboard.click/double_click` (이미 tools.py에 import 되어 있음).
- Produces: dispatch 반환 문자열이 `"clicked element {id} at {x},{y}"` / `"double_clicked element {id} at {x},{y}"`로 바뀜 (`(mouse fallback)` 접미사와 `"pressed element ..."` 문자열 소멸). 에러 문자열은 기존과 동일.

- [ ] **Step 1: 기존 테스트를 새 동작으로 재작성** — `tests/test_agent.py`에서:

`test_dispatch_click_element_falls_back_to_mouse`와 `test_dispatch_click_element_double_falls_back_to_mouse`(1146-1163행)를 다음으로 교체:

```python
def test_dispatch_click_element_clicks_with_mouse(mocker):
    mocker.patch("actions.accessibility.element_known", return_value=True)
    mock_activate = mocker.patch(
        "actions.accessibility.activate_target_app", return_value=True)
    mocker.patch("actions.accessibility.element_center", return_value=(120.0, 240.0))
    mock_click = mocker.patch("agent.tools.click")
    res = dispatch("click_element", {"id": 2})
    mock_activate.assert_called_once()
    mock_click.assert_called_once_with(120, 240)
    assert res == "clicked element 2 at 120,240"


def test_dispatch_click_element_double_clicks_with_mouse(mocker):
    mocker.patch("actions.accessibility.element_known", return_value=True)
    mocker.patch("actions.accessibility.activate_target_app", return_value=True)
    mocker.patch("actions.accessibility.element_center", return_value=(10.0, 20.0))
    mock_double = mocker.patch("agent.tools.double_click")
    res = dispatch("click_element", {"id": 1, "double": True})
    mock_double.assert_called_once_with(10, 20)
    assert res == "double_clicked element 1 at 10,20"
```

`test_dispatch_click_element_stale_element`(1172행 부근)에서 `mocker.patch("actions.accessibility.press_element", return_value=None)` 줄을 `mocker.patch("actions.accessibility.activate_target_app", return_value=True)`로 교체 (element_center None 모킹과 에러 assert는 유지).

`test_dispatch_click_element_prefers_ax_press`(~1276행, "independent actuation dispatch" 섹션) 전체 삭제.

`test_dispatch_click_element_unknown_id`, `test_dispatch_click_element_requires_int_id`는 그대로 둔다.

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_agent.py -q -k click_element`
Expected: 새로 쓴 2개 FAILED (반환 문자열에 `(mouse fallback)`이 남아 있고 activate 미호출), 나머지 PASS

- [ ] **Step 3: dispatch 구현 교체** — `agent/tools.py`의 click_element 분기(165-187행)를 다음으로 교체:

```python
    elif action == "click_element":
        try:
            element_id = int(params.get("id"))
        except (TypeError, ValueError):
            return "error: click_element requires integer param id"
        if not accessibility.element_known(element_id):
            return (f"error: 알 수 없는 요소 id {element_id} — "
                    "read_screen을 먼저 실행하세요")
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
```

- [ ] **Step 4: press_element 및 전용 헬퍼 삭제** — `actions/accessibility.py`에서 `press_element` 함수 전체, `_ax_actions`, `_ax_perform` 삭제 (`_ax_settable`/`_ax_set`은 set_element_value가 쓰므로 유지). `tests/test_actions.py`에서 `test_press_element_uses_ax_action`, `test_press_element_none_without_ax_action`, `test_press_element_double_prefers_axopen`, `test_press_element_none_when_perform_fails`(504-538행) 삭제.

- [ ] **Step 5: 통과 확인 (전체)**

Run: `python3 -m pytest tests/ -q`
Expected: 전체 통과 (베이스라인 508에서 테스트 수 증감 있음). `grep -rn "press_element" --include="*.py" .` 결과 0건 확인.

- [ ] **Step 6: 커밋**

```bash
git add agent/tools.py actions/accessibility.py tests/test_agent.py tests/test_actions.py
git commit -m "click_element를 AXPress에서 항상 실제 마우스 클릭으로 전환

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 포인터 액션 → 화면 조작 신호 훅 (tools.py)

**Files:**
- Modify: `agent/tools.py` (`set_text_input_provider` 근처에 훅 추가, 포인터 액션 분기에 호출 삽입)
- Test: `tests/test_agent.py` (dispatch 테스트 섹션에 추가)

**Interfaces:**
- Consumes: 없음 (독립 훅).
- Produces: `set_control_indicator_provider(provider) -> None` — provider는 `Callable[[bool], None]`. Task 4의 `main.py`가 `hud.set_screen_control`로 배선. dispatch는 `click_element`, `click`, `double_click`, `move_mouse`, `scroll` 실행 직전에 `provider(True)`를 호출한다 (끄는 건 HUD 몫).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_agent.py`, click_element dispatch 테스트들 뒤에 추가:

```python
def test_dispatch_pointer_actions_signal_screen_control(mocker):
    from agent import tools
    mocker.patch("agent.tools.click")
    mocker.patch("agent.tools.double_click")
    mocker.patch("agent.tools.move_mouse")
    mocker.patch("agent.tools.scroll")
    mocker.patch("agent.tools.last_capture_rect", return_value=(0, 0, 1000, 800))
    calls = []
    tools.set_control_indicator_provider(lambda on: calls.append(on))
    try:
        dispatch("click", {"x": 500, "y": 500})
        dispatch("double_click", {"x": 500, "y": 500})
        dispatch("move_mouse", {"x": 500, "y": 500})
        dispatch("scroll", {"direction": "down"})
        assert calls == [True, True, True, True]
    finally:
        tools.set_control_indicator_provider(None)


def test_dispatch_click_element_signals_screen_control(mocker):
    from agent import tools
    mocker.patch("actions.accessibility.element_known", return_value=True)
    mocker.patch("actions.accessibility.activate_target_app", return_value=True)
    mocker.patch("actions.accessibility.element_center", return_value=(10.0, 20.0))
    mocker.patch("agent.tools.click")
    calls = []
    tools.set_control_indicator_provider(lambda on: calls.append(on))
    try:
        dispatch("click_element", {"id": 1})
        assert calls == [True]
    finally:
        tools.set_control_indicator_provider(None)


def test_dispatch_non_pointer_actions_do_not_signal(mocker):
    from agent import tools
    mocker.patch("agent.tools.run_applescript", return_value="ok")
    calls = []
    tools.set_control_indicator_provider(lambda on: calls.append(on))
    try:
        dispatch("speak_only", {})
        dispatch("launch_app", {"app": "Safari"})
        assert calls == []
    finally:
        tools.set_control_indicator_provider(None)
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_agent.py -q -k screen_control`
Expected: FAILED — `AttributeError: module 'agent.tools' has no attribute 'set_control_indicator_provider'`

- [ ] **Step 3: 구현** — `agent/tools.py`의 `set_text_input_provider` 정의 아래에 추가:

```python
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
```

그리고 dispatch에서 다섯 분기에 호출 삽입:
- `click`/`double_click`/`move_mouse` 분기: `pt is None` 에러 리턴 **다음**, 실제 동작 호출 직전에 `_signal_screen_control()`
- `scroll` 분기: `pt = _to_logical(params) or (0, 0)` 다음 줄에 `_signal_screen_control()`
- `click_element` 분기: `element_known` 검증 통과 직후, `activate_target_app()` 호출 **직전**에 `_signal_screen_control()` (테두리가 조작 시작과 동시에 뜨도록)

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/test_agent.py -q`
Expected: 전체 통과

- [ ] **Step 5: 커밋**

```bash
git add agent/tools.py tests/test_agent.py
git commit -m "포인터 점유 액션에 화면 조작 표시 훅 추가

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: NotchHUD.set_screen_control + 자동 해제 + main 배선

**Files:**
- Modify: `ui/notch_hud.py` (`NotchHUD.__init__`에 플래그, `set_state` 수정, `set_screen_control` 추가 — `set_state`가 875행 부근)
- Modify: `main.py` (~305행, `agent_tools.set_text_input_provider(...)` 옆에 한 줄)
- Test: `tests/test_notch_hud.py`

**Interfaces:**
- Consumes: 기존 `_SwiftHUDBridge.send(payload: dict) -> bool`, 기존 `_ensure_init()`.
- Produces: `NotchHUD.set_screen_control(on: bool) -> None` — 중복 호출 dedupe, 브리지로 `{"type": "control", "on": <bool>}` 전송. `set_state(state)`는 state가 `"executing"`이 아니면 켜져 있던 screen control을 자동으로 끈다. Task 5의 Swift가 이 메시지를 소비.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_notch_hud.py` 끝에 추가:

```python
# ---------------------------------------------------------------------------
# Screen-control indicator
# ---------------------------------------------------------------------------

class _FakeBridge:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)
        return True


def _controllable_hud(monkeypatch):
    hud = NotchHUD()
    hud._initialized = True
    hud._bridge = _FakeBridge()
    monkeypatch.setattr(hud, "_ensure_init", lambda: None)
    monkeypatch.setattr(hud, "_dispatch_render", lambda: None)
    return hud


def test_set_screen_control_sends_control_message(monkeypatch):
    hud = _controllable_hud(monkeypatch)
    hud.set_screen_control(True)
    assert {"type": "control", "on": True} in hud._bridge.sent


def test_set_screen_control_dedupes_repeat_calls(monkeypatch):
    hud = _controllable_hud(monkeypatch)
    hud.set_screen_control(True)
    hud.set_screen_control(True)
    assert hud._bridge.sent.count({"type": "control", "on": True}) == 1


def test_screen_control_cleared_when_leaving_executing(monkeypatch):
    hud = _controllable_hud(monkeypatch)
    hud.set_state("executing")
    hud.set_screen_control(True)
    hud.set_state("success")
    assert {"type": "control", "on": False} in hud._bridge.sent


def test_screen_control_kept_while_still_executing(monkeypatch):
    hud = _controllable_hud(monkeypatch)
    hud.set_state("executing")
    hud.set_screen_control(True)
    hud.set_state("executing")
    assert {"type": "control", "on": False} not in hud._bridge.sent


def test_set_state_without_control_sends_nothing_extra(monkeypatch):
    hud = _controllable_hud(monkeypatch)
    hud.set_state("idle")
    assert all(p.get("type") != "control" for p in hud._bridge.sent)
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_notch_hud.py -q -k screen_control or set_state_without`
(주의: `-k "screen_control or set_state_without"` 인용 필요)
Expected: FAILED — `AttributeError: 'NotchHUD' object has no attribute 'set_screen_control'`

- [ ] **Step 3: 구현** — `ui/notch_hud.py`:

`__init__`의 `self._visible = False` 근처에 추가:

```python
        # True while the agent drives the real pointer (border + cursor ring)
        self._screen_control = False
```

`set_state` 맨 앞(첫 줄 `self._state = state` 다음)에 추가:

```python
        if state != "executing" and self._screen_control:
            # Pointer takeover is only meaningful while a command executes;
            # any other state means it ended (success, error, or idle).
            self.set_screen_control(False)
```

`set_state` 정의 뒤에 새 메서드 추가:

```python
    def set_screen_control(self, on: bool) -> None:
        """Show/hide the screen-takeover indicator (screen border + cursor
        ring) rendered by the Swift helper while VoiceDesk drives the mouse."""
        on = bool(on)
        if on == self._screen_control:
            return
        self._screen_control = on
        if on:
            self._ensure_init()
        if self._bridge is not None:
            self._bridge.send({"type": "control", "on": on})
```

`main.py` ~305행, `agent_tools.set_text_input_provider(hud.request_text_input)` 바로 아래에 추가 (import 별칭은 그 줄과 동일하게 사용):

```python
    agent_tools.set_control_indicator_provider(hud.set_screen_control)
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/test_notch_hud.py tests/test_main.py -q`
Expected: 전체 통과 (test_main.py에 사용자 미커밋 변경이 있음 — 실패가 나오면 이 변경 전 상태에서도 실패하는지 `git stash` 없이 원인만 확인하고, 이 태스크와 무관하면 그대로 보고)

- [ ] **Step 5: 커밋**

```bash
git add ui/notch_hud.py main.py tests/test_notch_hud.py
git commit -m "노치 HUD에 화면 조작 표시 상태 추가 및 실행 종료 시 자동 해제

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Swift 오버레이 — 화면 테두리 + 커서 링

**Files:**
- Modify: `ui/swift_hud/VoiceDeskHUD.swift` — `HUDController` 클래스(2097행~) 위에 오버레이 클래스들 추가, `HUDController`에 필드 1개 + `handle()`(2150행~)에 case 1개

**Interfaces:**
- Consumes: Task 4가 보내는 `{"type": "control", "on": true|false}`.
- Produces: on 동안 모든 화면에 파란 테두리 + 커서를 따라다니는 링(클릭 시 펄스). 모든 오버레이 창은 `ignoresMouseEvents = true`로 합성 클릭을 절대 가로채지 않는다.

- [ ] **Step 1: 오버레이 클래스 추가** — `private final class HUDController {` 바로 위에 삽입:

```swift
// MARK: - Screen-control overlay (border + cursor ring)

/// Shown while VoiceDesk drives the real mouse: a colored border around every
/// screen plus a halo ring that follows the cursor and pulses on clicks. All
/// windows ignore mouse events so they never intercept the synthetic clicks.
private final class CursorRingModel: ObservableObject {
    @Published var pulseID = 0
}

private let controlAccent = Color(red: 0.35, green: 0.65, blue: 1.0)

private struct ControlBorderView: View {
    var body: some View {
        RoundedRectangle(cornerRadius: 12)
            .strokeBorder(controlAccent.opacity(0.9), lineWidth: 4)
            .padding(2)
            .ignoresSafeArea()
    }
}

private struct CursorRingView: View {
    @ObservedObject var model: CursorRingModel
    @State private var pulsing = false
    var body: some View {
        Circle()
            .strokeBorder(controlAccent.opacity(0.9), lineWidth: 3)
            .background(Circle().fill(controlAccent.opacity(0.15)))
            .scaleEffect(pulsing ? 1.5 : 1.0)
            .opacity(pulsing ? 0.3 : 1.0)
            .animation(.easeOut(duration: 0.25), value: pulsing)
            .onChange(of: model.pulseID) { _ in
                pulsing = true
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                    pulsing = false
                }
            }
            .padding(4)
    }
}

private final class ControlOverlayController {
    private var borderWindows: [NSWindow] = []
    private var ringWindow: NSWindow?
    private var tracker: Timer?
    private var clickMonitor: Any?
    private let ringModel = CursorRingModel()
    private let ringSize: CGFloat = 44

    func set(on: Bool) {
        if on { show() } else { hide() }
    }

    private func show() {
        guard borderWindows.isEmpty else { return }
        for screen in NSScreen.screens {
            let window = overlayWindow(frame: screen.frame)
            window.contentView = NSHostingView(rootView: ControlBorderView())
            window.orderFrontRegardless()
            borderWindows.append(window)
        }
        let ring = overlayWindow(
            frame: NSRect(x: 0, y: 0, width: ringSize, height: ringSize))
        ring.contentView = NSHostingView(rootView: CursorRingView(model: ringModel))
        ring.orderFrontRegardless()
        ringWindow = ring
        moveRing()
        tracker = Timer.scheduledTimer(withTimeInterval: 1.0 / 60.0, repeats: true) { [weak self] _ in
            self?.moveRing()
        }
        // pyautogui's CGEvent clicks pass through the window server, so a
        // global monitor sees them and can drive the pulse animation.
        clickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown]) { [weak self] _ in
            self?.ringModel.pulseID += 1
        }
    }

    private func hide() {
        tracker?.invalidate()
        tracker = nil
        if let monitor = clickMonitor {
            NSEvent.removeMonitor(monitor)
            clickMonitor = nil
        }
        for window in borderWindows { window.orderOut(nil) }
        borderWindows.removeAll()
        ringWindow?.orderOut(nil)
        ringWindow = nil
    }

    private func moveRing() {
        guard let ring = ringWindow else { return }
        let p = NSEvent.mouseLocation
        ring.setFrameOrigin(NSPoint(x: p.x - ringSize / 2, y: p.y - ringSize / 2))
    }

    private func overlayWindow(frame: NSRect) -> NSWindow {
        let window = NSWindow(
            contentRect: frame,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.level = NSWindow.Level(
            rawValue: Int(CGWindowLevelForKey(.assistiveTechHighWindow)))
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.ignoresMouseEvents = true
        window.collectionBehavior = [
            .canJoinAllSpaces,
            .stationary,
            .ignoresCycle,
            .fullScreenAuxiliary,
        ]
        window.isReleasedWhenClosed = false
        return window
    }
}
```

- [ ] **Step 2: HUDController에 배선** — `HUDController` 안 `private var snapshot = HUDSnapshot()` 옆에 필드 추가:

```swift
    private let controlOverlay = ControlOverlayController()
```

`handle()`의 switch에 case 추가 (`case "hide":` 앞):

```swift
        case "control":
            controlOverlay.set(on: raw["on"] as? Bool ?? false)
```

`hide()` 함수(HUD 전체 숨김) 맨 앞에 `controlOverlay.set(on: false)` 한 줄 추가 — HUD가 내려가면 오버레이도 내려가야 한다.

- [ ] **Step 3: 타입체크**

Run: `xcrun swiftc -typecheck ui/swift_hud/VoiceDeskHUD.swift`
Expected: 출력 없이 exit 0. (`onChange(of:)` deprecation 경고는 무시 가능; 에러만 없으면 됨)

- [ ] **Step 4: 수동 스모크 테스트** (빌드 캐시가 소스 변경을 감지해 자동 재컴파일함):

```bash
python3 - <<'EOF'
import time
from ui.notch_hud import NotchHUD
hud = NotchHUD()
hud.show()
hud.set_state("executing")
hud.set_screen_control(True)
print("overlay ON — 5초간 테두리와 커서 링을 확인하세요")
time.sleep(5)
hud.set_state("success")   # must also clear the overlay
print("overlay OFF")
time.sleep(2)
EOF
```

Expected: 5초간 전 화면 파란 테두리 + 커서 따라다니는 링 표시, `set_state("success")` 후 즉시 사라짐. 링이 떠 있는 동안 커서 아래 창 클릭이 정상 동작(오버레이가 가로채지 않음).

- [ ] **Step 5: 커밋**

```bash
git add ui/swift_hud/VoiceDeskHUD.swift
git commit -m "Swift HUD에 화면 조작 테두리와 커서 링 오버레이 추가

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: 시스템 프롬프트 갱신 + 전체 검증

**Files:**
- Modify: `agent/context.py:20`, `agent/context.py:60-65`
- Test: 기존 스위트 전체 (프롬프트 존재-검사 테스트는 키워드만 확인하므로 수정 불필요)

**Interfaces:**
- Consumes: Task 2의 실제 동작 (마우스 글라이드 클릭 + 대상 앱 전면화).
- Produces: 프롬프트 서술과 런타임 동작 일치.

- [ ] **Step 1: 액션 목록 줄 수정** — `agent/context.py:20`:

교체 전:
```
- click_element    params: {"id": <int>}                   — press element [id] via Accessibility (NO mouse movement; add "double": true to open/double-click)
```
교체 후:
```
- click_element    params: {"id": <int>}                   — glide the mouse to element [id] and click it (add "double": true to open/double-click)
```

- [ ] **Step 2: 6번 항목 서술 수정** — `agent/context.py:60-65`:

교체 전:
```
   The agent works on a TARGET app — the app opened by launch_app or the
   app of the first read_screen — and keeps driving it even if the user
   focuses another window. click_element presses via Accessibility (the
   user's mouse never moves); to type into a field, prefer set_value with
   the field's id. type_text/press_key act on the FOCUSED app and may
   interfere with the user — use them only when set_value fails.
```
교체 후:
```
   The agent works on a TARGET app — the app opened by launch_app or the
   app of the first read_screen — and keeps driving it even if the user
   focuses another window. click_element brings the target app to the
   front, glides the REAL mouse cursor to the element and clicks it (the
   user sees a takeover indicator while this happens); to type into a
   field, prefer set_value with the field's id. type_text/press_key act
   on the FOCUSED app and may interfere with the user — use them only
   when set_value fails.
```

- [ ] **Step 3: 전체 스위트 실행**

Run: `python3 -m pytest tests/ -q`
Expected: 전체 통과. 알려진 플레이크 2건이 실패하면 단독 재실행(`-k` 지정)으로 통과 확인 후 진행.

- [ ] **Step 4: 커밋**

```bash
git add agent/context.py
git commit -m "시스템 프롬프트의 click_element 서술을 마우스 클릭 동작에 맞게 갱신

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
