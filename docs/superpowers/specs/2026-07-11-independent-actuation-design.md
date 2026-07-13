# Independent Actuation — 사용자와 간섭 없는 백그라운드 조작 설계

날짜: 2026-07-11
상태: 승인됨 (사용자가 Track A 진행 선택)
선행: `2026-07-10-window-use-design.md` (AX 스냅샷/click_element 기반 위에 얹음)

## 1. 목표

VoiceDesk가 명령을 수행하는 동안 **사용자의 마우스·포커스·클립보드를 건드리지
않는다**. 사용자는 다른 앱에서 계속 작업하고, VoiceDesk는 자신이 여는/조작하는
앱을 백그라운드에서 독립적으로 다룬다.

## 2. 근본 원인 (조사 완료 — 재현 증거 있음)

| 간섭 지점 | 현재 구현 | 영향 |
|---|---|---|
| 클릭 | `click_element`가 AX 좌표를 얻고도 **실제 마우스**(pyautogui)로 클릭 | 사용자 포인터 강탈 |
| 텍스트 입력 | 한글 `type_text` = `pbcopy` + `Cmd+V` | 클립보드 파괴 + 포커스된(사용자) 창에 입력 |
| 대상 선정 | `read_screen`/스크린샷이 **프론트 앱** 기준 | 사용자가 앱을 바꾸면 사용자 앱을 조작 |
| 앱 실행 | AppleScript `activate` | 포커스 강탈 |

실증: 이 기기에서 **비프론트(백그라운드) 앱의 AX 트리 순회, 버튼의 `AXPress`
액션 노출, `AXValue` 설정 가능 여부 조회**가 모두 동작함을 확인
(프로브 출력: background Terminal button actions `['AXPress']`). AX 액션은
커서·포커스·클립보드를 전혀 사용하지 않는다.

## 3. 설계

### 3.1 대상 앱 고정 (target pinning)

- `actions/accessibility.py`에 모듈 상태 `대상 pid` 추가:
  - `set_target_app(name: str) -> bool` — 실행 중인 앱 이름으로 pid 해석·고정
  - `clear_target_app()` — 해제
- `agent/core.py`: `run()` 시작 시 `clear_target_app()` (명령마다 초기화).
- `agent/tools.py`: `launch_app` 성공 시 그 앱을 대상으로 고정.
- `snapshot_screen()`: 대상이 고정돼 있으면 **그 pid**를 순회 (프론트 무관);
  없으면 기존처럼 프론트 앱을 순회하되 **그 앱을 대상으로 고정**.
  → 명령 수행 중 사용자가 다른 앱으로 전환해도 VoiceDesk는 자기 대상만 본다.
- 대상 앱이 종료되면 error 반환 ("대상 앱이 종료되었어요 — …").

### 3.2 클릭: AXPress 우선, 실제 마우스는 폴백

`click_element` 순서:
1. 요소의 `AXActionNames`에 `AXPress`가 있으면 `AXUIElementPerformAction`
   수행 — 커서 이동 없음, 백그라운드 동작. 결과: `pressed element N`.
2. `double: true`이고 `AXOpen` 액션이 있으면 그것을 수행 (Finder 등).
3. AX 액션이 없거나 수행이 실패하면 기존 실제 마우스 클릭으로 폴백하고
   결과 문자열에 간섭 표시를 남긴다: `clicked element N at x,y (mouse fallback)`.

### 3.3 텍스트 입력: `set_value` 액션 신설

- `set_value` params `{"id": <int>, "text": "<text>"}` —
  `AXUIElementSetAttributeValue(elem, "AXValue", text)`.
  클립보드·키보드·포커스 불사용.
- 설정 불가(`AXUIElementIsAttributeSettable` false) 또는 실패 시 error 반환
  (모델이 폴백으로 click_element 후 type_text 선택 가능 — 프롬프트에 명시).
- 긴 텍스트 확인 게이트(`_TEXT_INPUT_MIN_CHARS` = 10, HUD 확인)는 type_text와
  동일하게 적용 — 받아쓰기 오류 방지 목적은 입력 방식과 무관.

### 3.4 프롬프트 규칙 (`agent/context.py`만)

- click_element가 AXPress로 동작함(마우스 불사용)을 명시.
- 텍스트필드 입력은 `set_value`가 기본, type_text는 폴백임을 명시.
- read_screen이 "대상 앱"(직전 launch_app 또는 첫 read_screen 시점의 앱)을
  계속 대상으로 함을 명시 — 사용자가 화면을 바꿔도 무관.

### 3.5 유지(변경하지 않음)

- `launch_app`의 `activate` — 사용자가 명시적으로 앱을 열라고 한 것이므로
  화면에 보여주는 게 의도. 이후 조작은 pin 덕에 포커스가 필요 없다.
- 스크린샷+그리드+좌표 클릭 폴백 경로 — AX 미지원 앱용. 이 경로는 본질적으로
  간섭형이며 그대로 둔다 (개선 아이디어: 창 단위 캡처 `screencapture -l` — 후속).
- press_key / scroll — 실제 키보드/스크롤 이벤트 (폴백 모드 전용으로 프롬프트에 강등).

## 4. 오류 처리

| 상황 | 동작 |
|---|---|
| 대상 앱 종료됨 | `error: 대상 앱이 종료되었어요` → done-gate가 거짓 완료 차단 |
| AXPress 수행 실패(err != 0) | 실제 마우스 클릭 폴백 + `(mouse fallback)` 표기 |
| set_value 설정 불가 | `error: 이 요소에는 값을 직접 넣을 수 없어요 — click_element 후 type_text를 쓰세요` |
| set_target_app에 없는 앱 이름 | False 반환, launch_app 결과에는 영향 없음 (pin 실패만 로그) |

## 5. 캐시·안전

- `set_value`는 스냅샷 의존 → `_UNCACHEABLE_ACTIONS`에 추가.
- SafetyGuard는 기존처럼 action+params 문자열 검사 (`set_value`의 text가
  위험 키워드를 포함하면 기존 로직이 잡는다).

## 6. 테스트 (전부 모킹)

- AXPress 우선: 액션 목록에 AXPress 있으면 perform 호출, 마우스 클릭 미호출.
- AXPress 실패/부재 시 마우스 폴백 + `(mouse fallback)` 문자열.
- double + AXOpen 경로.
- set_value: 성공 / settable=false 오류 / 확인 게이트(>=10자) 적용.
- target pinning: set_target_app 후 snapshot_screen이 프론트 대신 대상 pid 사용;
  run() 시작 시 clear; launch_app 성공 시 pin.
- 대상 앱 소멸 시 error.
- 프롬프트 문서화 assert.
- 기존 window-use·스크린샷 경로 테스트 회귀 없음.

## 7. 범위 제외

- 웨이크워드(Track B — 별도 스펙으로 보류, 조사 결과는 본 문서 상단 링크 참조)
- 창 단위 스크린샷 캡처, CGEventPostToPid 방식 이벤트 주입
- 스크롤/단축키의 비간섭화
