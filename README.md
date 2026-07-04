# VoiceDesk

한국어 음성 명령으로 macOS를 제어하는 데스크톱 AI 에이전트입니다. 웨이크워드(또는 단축키)로
말을 걸면, 앱 실행·웹 검색·화면을 보고 클릭하는 컴퓨터 유즈까지 하나의 ReAct 루프가 알아서
단계별로 수행하고 결과를 음성으로 답합니다.

```
웨이크워드/단축키 → STT(음성 인식) → LLM ReAct 루프 → macOS 액션 → TTS(음성 응답)
```

## 주요 기능

- **웨이크워드 활성화**: "Hey Jarvis" / "Hey Desk" 또는 `Option+Space` 단축키로 명령 시작
- **다단계 ReAct 에이전트**: 한 번의 명령을 여러 단계로 나눠 수행 — 실행 결과를 관찰하고
  성공을 검증한 뒤에만 완료로 처리 (예: "크롬 열고 지메일 검색해줘")
- **컴퓨터 유즈**: 비전 지원 LLM이 스크린샷을 보고 화면 속 버튼/링크를 실제 좌표로 클릭
- **다중 STT/LLM/TTS 프로바이더**: Whisper(로컬/API), macOS 내장 STT / Claude, OpenAI, NVIDIA
  NIM, Ollama / macOS 내장 음성, NVIDIA Chatterbox TTS — 설정에서 자유롭게 교체
- **안전 장치(SafetyGuard)**: 삭제·발송·결제 등 위험한 동작은 실행 전 확인을 요구하고,
  실패한 동작에 대해서는 완료(done)를 선언하지 못하도록 차단
- **노치 HUD**: 상태(듣는 중/처리 중/성공/오류)를 보여주는 macOS 노치 스타일 위젯 (Swift)
- **루틴 & 메트릭**: 반복되는 명령은 캐시/루틴으로 저장하고, 인식률·성공률·응답 시간을
  설정 창의 대시보드에서 확인

## 아키텍처

| 경로 | 역할 |
|---|---|
| `main.py` | 오케스트레이터: 컴포넌트 연결, 메뉴바, 설정 변경 핫리로드 |
| `activation/` | 웨이크워드(openwakeword) + 단축키 감지 |
| `stt/` | 음성 인식 어댑터 (whisper 로컬/API, macOS) |
| `llm/` | LLM 프로바이더 어댑터 (Claude, OpenAI, NVIDIA, Ollama) — 시스템 프롬프트는 공유 |
| `agent/` | 실행 코어: `context.py`(시스템 프롬프트), `core.py`(ReAct 루프), `tools.py`(액션 디스패치), `cache.py`(핫 커맨드 캐시) |
| `actions/` | macOS 이펙터: AppleScript, 마우스/키보드, 화면 캡처, TTS |
| `safety/` | SafetyGuard — 위험 동작 차단/확인 |
| `routines/` | 반복 명령 감지 및 저장된 루틴 |
| `metrics/` | 명령 성공률/응답시간 수집 |
| `ui/` | 노치 HUD(Swift), 설정 창, 메뉴바 |

## 빠른 시작

```bash
pip3 install -r requirements.txt   # Python 3.12+
python3 main.py                    # macOS 권한 허용 필요 (마이크, 손쉬운 사용, 화면 녹화 등)
```

설치·권한 설정·프로바이더별 설정·사용법·트러블슈팅까지 전체 가이드는
[`SETUP.md`](SETUP.md)를 참고하세요.

`.app`/DMG로 패키징하려면:

```bash
python3 setup.py py2app
```

## 테스트

```bash
python3 -m pytest tests/ -q
```

모든 테스트는 네트워크·실제 마우스/화면 접근 없이 완전히 모킹되어 있습니다.

## 기술 스택

Python 3.12+ · Anthropic / OpenAI / NVIDIA NIM / Ollama SDK · SpeechRecognition ·
faster-whisper · openwakeword · pyobjc (macOS 권한·오토메이션) · Swift (노치 HUD)
