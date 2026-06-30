# VoiceDesk — 설치 및 실행 가이드

## 시스템 요구사항

| 항목 | 최소 사양 |
|---|---|
| macOS | 12 Monterey 이상 |
| CPU | Apple Silicon (M1+) 또는 Intel |
| Python | 3.12 이상 |
| 여유 용량 | 최소 2GB (로컬 AI 모델 사용 시 추가 필요) |

---

## 1. 설치

```bash
git clone https://github.com/your-org/voicedesk.git
cd voicedesk
pip3 install -r requirements.txt
```

---

## 2. macOS 권한 설정 (필수)

앱을 처음 실행하기 전에 아래 권한 3가지를 허용해야 합니다.

### 마이크 접근
`시스템 설정 → 개인정보 보호 및 보안 → 마이크 → Terminal (또는 VoiceDesk.app) 허용`

### 손쉬운 사용 (Accessibility)
`시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용 → Terminal (또는 VoiceDesk.app) 허용`

> 이 권한이 없으면 마우스/키보드 제어, 앱 버튼 클릭 등이 동작하지 않습니다.

### 화면 녹화
`시스템 설정 → 개인정보 보호 및 보안 → 화면 및 시스템 오디오 녹화 → Terminal (또는 VoiceDesk.app) 허용`

> 화면 캡처 기반 검증 기능에 필요합니다.

---

## 3. LLM / STT 설정

`config.yaml`을 열어 사용할 프로바이더를 선택합니다.

### 옵션 A — 완전 무료 (로컬)

```yaml
stt:
  provider: whisper_local
  whisper_local_model: base   # tiny / base / small / medium 중 선택

llm:
  provider: ollama
  ollama_url: http://localhost:11434
  ollama_model: llama3
```

**Ollama 설치:**
```bash
brew install ollama
ollama pull llama3   # 약 4GB 다운로드
ollama serve         # 백그라운드 실행
```

**faster-whisper 모델 다운로드:**
첫 실행 시 자동으로 다운로드됩니다 (base 모델 약 140MB).

---

### 옵션 B — Claude API 사용 (권장)

```yaml
stt:
  provider: whisper_local   # STT는 로컬로 무료 유지

llm:
  provider: claude
  claude_api_key: sk-ant-...   # Anthropic Console에서 발급
  claude_model: claude-sonnet-4-6
```

**API 키 발급:** https://console.anthropic.com → API Keys

**예상 비용:** 하루 30회 사용 기준 약 $7/월 (Hot Command Cache 절감 포함)

---

### 옵션 C — OpenAI GPT-4o 사용

```yaml
stt:
  provider: whisper_api
  whisper_api_key: sk-...   # OpenAI API 키

llm:
  provider: openai
  openai_api_key: sk-...
  openai_model: gpt-4o
```

---

## 4. 실행

```bash
python3 main.py
```

메뉴 바에 VoiceDesk 아이콘이 나타나면 준비 완료입니다.

---

## 5. 사용 방법

### 음성 명령 시작

| 방법 | 동작 |
|---|---|
| **⌥Space** (Option + Space) | 5초 녹음 후 명령 실행 |
| **"Hey Desk"** (웨이크 워드) | 자동 인식 후 명령 실행 |

> 활성화 방법은 Settings → General에서 변경 가능

### 명령 예시

```
"사파리 열어줘"
"볼륨 줄여줘"
"화면 캡처해줘"
"메일 앱에서 새 메일 작성해줘"
"지금 열려있는 창 닫아줘"
"Spotify에서 다음 곡 틀어줘"
```

### 위험 명령 확인

삭제, 이메일 발송, 구매 등 위험한 작업은 실행 전 음성으로 확인을 요청합니다:
> "위험한 작업입니다. 진행할까요? 네 또는 아니오로 말씀해주세요."

---

## 6. Settings UI 열기

메뉴 바 아이콘 클릭 → **Open Settings**

| 페이지 | 설정 내용 |
|---|---|
| General | 웨이크 워드, 단축키, TTS 음성 |
| STT | 음성 인식 프로바이더 및 API 키 |
| LLM | AI 모델 프로바이더, API 키, 모델 선택 |
| Routines | 저장된 루틴 관리 |
| Metrics | 6개 KPI 대시보드 |
| About | 버전 정보 |

> STT/LLM 변경 후 Save하면 **재시작 없이 즉시 적용**됩니다.

---

## 7. .app 번들로 실행 (선택)

개발이 완료된 후 배포용 앱으로 빌드할 수 있습니다:

```bash
python setup.py py2app
open dist/VoiceDesk.app
```

---

## 트러블슈팅

| 증상 | 해결 방법 |
|---|---|
| 음성이 인식되지 않음 | 마이크 권한 확인 (항목 2) |
| "클릭" 동작이 안 됨 | 손쉬운 사용(Accessibility) 권한 확인 |
| Ollama 연결 실패 | `ollama serve` 실행 여부 확인 |
| Claude API 오류 | `claude_api_key` 값 확인 |
| faster-whisper 느림 | `whisper_local_model: tiny`로 변경 |
| 화면 캡처 안 됨 | 화면 녹화 권한 확인 (항목 2) |
