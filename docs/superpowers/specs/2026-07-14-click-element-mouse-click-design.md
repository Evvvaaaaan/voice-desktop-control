# click_element 마우스 클릭 전환 + 화면 조작 표시 설계

날짜: 2026-07-14
상태: 승인됨 (설계 리뷰 완료)

## 목표

`click_element`를 AXPress(접근성 액션) 방식에서 **항상 실제 마우스 클릭** 방식으로
전환하고, VoiceDesk가 화면을 조작하는 동안 사용자가 그 사실을 명확히 인지할 수
있도록 (1) 노치 HUD + 화면 테두리로 "조작 중" 표시, (2) 커서 하이라이트 링을
표시한다.

## 배경 / 현재 동작

- `agent/tools.py`의 `click_element`는 `accessibility.press_element`(AXPress)를
  우선 시도하고, AX 액션이 없는 요소만 실제 마우스 클릭으로 폴백한다.
- AXPress는 커서가 움직이지 않고 백그라운드 앱에도 동작하지만, 사용자는
  VoiceDesk가 무엇을 하는지 시각적으로 알 수 없다.
- 마우스 클릭 인프라(`actions/mouse_keyboard.py`)는 이미 글라이드 이동
  (0.45초 easeInOutQuad) 후 클릭하는 computer-use 스타일로 구현되어 있다.
- Swift 노치 HUD는 단일 헬퍼 프로세스로, `_SwiftHUDBridge`가 JSON-line
  (stdin: `render`/`hide`/`quit`, stdout: 이벤트)으로 통신한다.

## 결정 사항 (사용자 확인 완료)

1. **클릭 방식**: AXPress 경로 완전 제거, 항상 마우스 클릭.
2. **사용 중 표시**: 노치 HUD 상태 + 화면 테두리 오버레이 둘 다.
3. **커서 표시**: 실제 커서를 따라다니는 하이라이트 링 오버레이
   (시스템 커서 교체 아님).

## 설계

### 1. click_element — 항상 마우스 클릭

`agent/tools.py` `click_element` 분기:

1. `element_known(id)` 검증 (기존 유지 — 오래된 id 에러 메시지 동일).
2. `accessibility.activate_target_app()` — 대상 앱(`_TARGET_PID`)을 전면으로
   가져온다. **필수**: 전역 좌표 클릭은 그 지점의 최상단 창에 떨어지므로,
   대상 앱이 백그라운드면 다른 앱을 잘못 클릭한다.
3. `element_center(id)`로 클릭 직전에 좌표를 새로 읽는다 (창 이동 대응,
   기존 구현 재사용). None이면 기존 "요소가 더 이상 존재하지 않아요" 에러.
4. `click(x, y)` 또는 `double`이면 `double_click(x, y)` — 글라이드 이동 포함.

`actions/accessibility.py`:

- `activate_target_app()` 추가: `_TARGET_PID`의 앱을
  `NSRunningApplication.activate` (또는 AppleScript activate)로 전면화.
  대상이 없으면 no-op(전면 앱 유지).
- `press_element`는 사용처가 없어지므로 제거. 관련 테스트 수정.
- `set_element_value`(set_value)는 변경 없음 — AX 직접 설정 유지.

`agent/context.py` 시스템 프롬프트: "click_element presses via Accessibility
(the user's mouse never moves)" 서술을 실제 동작(마우스가 요소로 이동해
클릭하며, 조작 중 표시가 뜬다)에 맞게 수정.

캐시 안전 규칙(click_element/read_screen/set_value 캐시 제외)은 변경 없음.

### 2. 화면 조작 표시 — 노치 HUD + 화면 테두리

**Swift** (`ui/swift_hud/VoiceDeskHUD.swift`): 새 메시지 타입
`{"type": "control", "on": true|false}` 추가.

- on: 모든 NSScreen 가장자리에 색 테두리를 그리는 오버레이 창 표시.
  borderless, 투명 배경, `ignoresMouseEvents = true`, 높은 window level —
  클릭과 포인터 이벤트를 완전히 통과시킨다.
- off: 테두리 창과 커서 링 창 제거.
- 노치 스트립 자체는 기존 `executing` 상태 렌더링을 그대로 활용한다.

**Python** (`ui/notch_hud.py`):

- `NotchHUD.set_screen_control(on: bool)` 추가 — 브리지로 `control` 메시지
  전송.
- `NotchHUD.set_state()`가 `executing`이 아닌 상태(success/error/idle 등)로
  전환될 때 켜져 있던 screen control을 자동으로 끈다. `agent/core.py`는
  손대지 않는다.

**Python** (`agent/tools.py`):

- 기존 `set_text_input_provider` 패턴과 동일한 훅
  `set_control_indicator_provider(provider)` 추가. `main.py`에서
  `hud.set_screen_control`로 배선.
- 포인터를 점유하는 액션 — `click_element`, `click`, `double_click`,
  `move_mouse`, `scroll` — 의 dispatch 직전에 `provider(True)` 호출.
  provider 미배선(테스트 등)이면 no-op.

### 3. 커서 하이라이트 링 (Swift)

- `control on` 동안 실제 커서 위치를 따라다니는 색 링/할로 오버레이 창을
  표시. 타이머 기반으로 `NSEvent.mouseLocation`을 폴링해 위치 갱신.
  클릭 통과(ignoresMouseEvents).
- 전역 `leftMouseDown` 모니터로 클릭 순간 펄스 애니메이션 재생.
  pyautogui가 포스트하는 CGEvent도 윈도우 서버를 거치므로 전역 모니터에
  잡힌다.
- 시스템 커서 이미지는 교체하지 않는다.

### 4. 테스트 (전부 모킹, 기존 관례)

- `click_element`: activate → 좌표 클릭 순서 호출 검증, `double` 처리,
  미지의 id / 소멸한 요소 에러 유지 검증.
- `press_element` 제거에 따른 기존 테스트 정리.
- control 훅: 포인터 액션 dispatch 시 `provider(True)` 호출, 비포인터 액션
  (launch_app, open_url, speak_only 등)은 미호출 검증.
- `NotchHUD.set_state` 전환 시 screen control 자동 해제 검증.
- Swift 쪽은 기존 관례대로 단위 테스트 제외 (수동 확인).

## 예상 정확도 (미검증 추정)

- 클릭 위치 자체는 AX 프레임 중심을 클릭 직전에 재조회하므로 사실상 결정적.
- 명령 단위 성공률은 약 90~95%로 추정하나 실측 전이다. 남는 실패 요인:
  글라이드 0.45초 사이 요소 이동(애니메이션 UI), 중심이 클릭 영역이 아닌
  커스텀 컨트롤, activate 직후 창 정렬 지연. 반대로 기존 AXPress 미지원
  요소는 오히려 성공하게 된다.
- `metrics/`의 명령 성공률 수집으로 배포 후 before/after 실측 비교한다.

## 트레이드오프 / 대안 검토

- 오버레이 구현 위치: 기존 Swift HUD 헬퍼 확장(채택) vs 별도 오버레이
  프로세스(인프라 중복) vs Python/PyObjC 창(이벤트 루프 부재로 불안정).
- AXPress 폴백 유지 여부: 제거(채택 — 동작 일관성) vs 유지(성공률은 높지만
  동작이 두 갈래).
- 백그라운드 조작 능력 상실: 마우스 클릭 전환의 의도된 결과. 대상 앱을
  전면화하고 조작 중임을 표시하는 것이 이 설계의 목적이다.
