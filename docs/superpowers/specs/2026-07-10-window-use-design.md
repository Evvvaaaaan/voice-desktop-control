# Window Use — AX 기반 구조화 화면 제어 설계

날짜: 2026-07-10
상태: 사용자 검토 대기

## 1. 목표

claude-in-chrome이 브라우저 DOM을 구조화된 요소 목록(`read_page`)으로 읽고 요소
단위로 조작하듯, VoiceDesk의 LLM 에이전트가 macOS 접근성(AX) 트리를 읽어
**요소 번호로 클릭**하게 한다. 기대 효과:

- **속도**: 매 스텝 스크린샷(200KB+ PNG) 업로드 + 비전 추론 왕복 제거.
  텍스트 요소 목록은 수 KB.
- **정확도**: 좌표를 비전 모델이 그리드에서 눈대중으로 추정하는 대신,
  AX가 보고하는 요소의 정확한 중심 좌표를 클릭 — 미스클릭 원인 제거.
- **호환성**: 비전 미지원 LLM(NVIDIA minimax 등)도 화면 제어 가능해짐.

근거: `scratch/probe_ax.py`, `probe_ax2.py`에서 pyobjc AX 트리 워크가 동작하고
ms 단위로 완료되며, Chromium 계열은 `AXEnhancedUserInterface` 플래그로 웹
콘텐츠 트리가 노출됨을 확인함.

## 2. 검토한 접근

| 접근 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **A. AX 우선 + 스크린샷 폴백 (채택)** | 빠르고 정확, 비전 미지원 모델 지원, 기존 경로 보존 | 두 경로 공존으로 프롬프트 규칙 추가 필요 | ✅ |
| B. AX로 전면 대체 | 코드 단순 | AX 트리 없는 앱(게임, 캔버스 UI)에서 제어 불능 | ❌ |
| C. 스크린샷 유지 + AX 좌표 보정만 | 변경 폭 최소 | 이미지 전송 지연 그대로, 비전 미지원 모델 문제 미해결 | ❌ |

사용자 확인 질문에 응답이 없어 추천안 A로 진행 (변경 원하면 이 문서 수정).

## 3. 아키텍처

```
agent/context.py   SYSTEM_PROMPT에 read_screen / click_element 추가, 규칙 개정
agent/core.py      요소 액션 후 관찰(observation)을 "신선한 요소 목록 텍스트"로 구성
agent/tools.py     dispatch에 read_screen / click_element 분기 추가
actions/accessibility.py   AX 스냅샷 워커 + 요소 클릭 (기존 레거시 함수는 유지)
```

기존 screenshot / click(x,y) / 그리드 경로는 **그대로 유지** — AX가 부실한
앱에서의 폴백.

### 3.1 새 dispatch 액션

- `read_screen` params `{}`
  - 프론트 앱의 AX 트리를 걸어 인터랙티브 요소를 번호 목록으로 반환:
    ```
    현재 앱: Google Chrome — 창: "받은편지함 - Gmail"
    [1] 버튼 "뒤로"
    [2] 텍스트필드 "주소창" 값="mail.google.com"
    [3] 링크 "받은편지함 (3)"
    ...
    ```
  - 반환 텍스트가 그대로 관찰로 모델에 전달된다.
- `click_element` params `{"id": <int>, "double": <bool, 기본 false>}`
  - 직전 스냅샷의 요소 id를 조회 → **클릭 시점에 AXPosition/AXSize를 다시
    읽어** 최신 중심 좌표 계산(창 이동 대비) → 기존 `click()`/`double_click()`
    실제 마우스 클릭 재사용.

### 3.2 AX 스냅샷 워커 (`actions/accessibility.py`)

- 프론트 앱 pid → `AXUIElementCreateApplication`, 메시징 타임아웃 0.3s,
  Chromium 플래그(`AXEnhancedUserInterface`, `AXManualAccessibility`) 설정.
- 반복(비재귀) 워크, 하드 캡: 방문 6,000 노드 / 깊이 25 / 목록 150개 /
  창 최대 2개. probe 실측 기준 일반 앱 수백 ms 이내.
- 수집 대상 롤: AXButton, AXLink, AXTextField, AXTextArea, AXCheckBox,
  AXRadioButton, AXPopUpButton, AXComboBox, AXMenuButton, AXMenuItem,
  AXSlider, AXDisclosureTriangle, AXTabGroup (probe_ax.py의 INTERACTIVE 집합과 동일).
- 각 요소: 롤(한국어 라벨), 제목/설명/값(40자 절단), 활성 여부, 중심 좌표.
  크기 0 또는 화면 밖 요소는 제외.
- 모듈 상태로 `id → AXUIElement 참조` 스냅샷 보관. **read_screen을 다시
  호출하면 이전 id는 전부 무효** (스냅샷 세대 교체).

### 3.3 관찰(observation) 변경 (`agent/core.py::_observe`)

- `click_element` 후: 짧은 안정화 대기(0.4s) 후 **새 read_screen 텍스트
  요약**을 관찰로 전달 — 비전 모델 여부와 무관하게 텍스트만. 클릭 결과
  검증(메뉴 열림, 페이지 전환)을 요소 목록 변화로 확인 가능.
- 기존 좌표 액션(click, move_mouse 등)의 스크린샷 관찰은 현행 유지.

### 3.4 프롬프트 규칙 (`agent/context.py`만 수정 — 어댑터에 프롬프트 금지)

- 화면 요소 조작은 **read_screen → click_element가 기본 경로**.
- read_screen 결과가 "요소가 거의 없음/AX 미지원"이면 스크린샷+그리드
  경로로 폴백하라는 규칙.
- id는 최신 read_screen 기준으로만 유효하다는 규칙.

## 4. 오류 처리 · 폴백

| 상황 | 동작 |
|---|---|
| AX 권한 없음 (`AXIsProcessTrusted()` false) | read_screen이 `error: 접근성 권한 필요 — 설정에서 허용` 반환. 권한 요청 UI는 이미 존재(page_permissions.py) |
| 인터랙티브 요소 < 5개 | 목록과 함께 "요소가 적음 — 스크린샷 폴백 권장" 문구를 결과에 포함 |
| 알 수 없는/무효 id | `error: 알 수 없는 요소 id — read_screen을 먼저 실행` → 기존 done-gate가 오류 시 done=true 거부 |
| 요소가 사라짐(위치 재조회 실패) | `error: 요소가 더 이상 존재하지 않음 — read_screen으로 다시 확인` |
| AX 워크 중 예외 | 오류 문자열 반환, 앱은 계속 동작 (스크린샷 경로 이용 가능) |

## 5. 안전 · 캐시

- `click_element`는 기존 `click`과 동일하게 SafetyGuard 검사를 통과해야 함.
- **핫 캐시 제외**: `read_screen`/`click_element`는 스냅샷 의존적이라 재생
  불가 → `agent/core.py`의 단일 스텝 캐시 기록에서 제외 (speak_only와 동일
  취급). 기존 "캐시는 재생 안전한 액션만" 원칙의 연장.

## 6. 테스트 (전부 모킹 — 프로젝트 규약)

- AX 호출은 `actions/accessibility.py` 내 소형 프라이빗 헬퍼(`_ax_attr` 등)
  뒤에 격리 → 테스트에서 monkeypatch로 가짜 트리(dict) 주입.
- 케이스: 요소 수집·번호 매김·포맷 / 캡 준수 / click_element가 최신 좌표로
  실제 클릭 호출 / 무효·스테일 id 오류 / 요소 부족 시 폴백 문구 /
  권한 없음 오류 / 캐시 제외 / 프롬프트에 새 액션 포함 /
  click_element 관찰이 텍스트 요소 목록인지.
- 기존 스크린샷 경로 테스트는 변경 없이 통과해야 함 (회귀 없음 증명).

## 7. 범위 제외 (YAGNI)

- 메뉴바/메뉴 항목 트리 추출 (필요 시 후속)
- AXPress 등 AX 액션 직접 실행 (실제 마우스 클릭으로 통일)
- AX로 텍스트 값 직접 설정 (기존 type_text + 확인 플로 유지)
- 백그라운드(비프론트) 앱 제어, 창 3개 이상 처리
- 레거시 `click_element_by_name` 정리 (미사용이지만 이번 범위 아님 — 언급만)

## 8. 성공 기준

1. 비전 미지원 LLM으로 "크롬에서 첫 번째 링크 눌러줘"류 명령이 스크린샷
   없이 완료된다.
2. 요소 클릭 스텝의 왕복 페이로드가 이미지(수백 KB) → 텍스트(수 KB)로 감소.
3. 전체 테스트 스위트(기존 167+신규) 통과, 기존 스크린샷 경로 회귀 없음.
