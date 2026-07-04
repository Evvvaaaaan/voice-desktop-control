# TODO — 남은 작업 (실제 사용 전 확인 필요)

이번 세션에서 코드/테스트는 모두 완료됐지만(167/167 통과), **API 키 발급·기기 실행·실제 음성 확인**은
제가 대신 할 수 없는 부분입니다. 아래를 순서대로 진행하세요.

---

## 1. 의존성 설치 (필수)

`nvidia-riva-client`가 `requirements.txt`에 새로 추가됐습니다.

```bash
cd /Users/evan/voicedesk
pip3 install -r requirements.txt
```

- [ ] 설치 완료 확인 (`python3 -c "import riva.client"` 에러 없이 실행되면 OK)

---

## 2. NVIDIA LLM 사용하려면

1. [ ] https://build.nvidia.com 에서 무료 계정 생성 (신용카드 불필요)
2. [ ] 아무 모델 페이지(예: `minimaxai/minimax-m3`)에서 **Get API Key** 클릭 → `nvapi-...` 키 발급
3. [ ] VoiceDesk 실행 → 메뉴바 아이콘 → **Open Settings → LLM 탭**
4. [ ] 프로바이더를 `nvidia`로 변경, 발급받은 API 키 붙여넣기
5. [ ] 모델명은 기본값(`minimaxai/minimax-m3`) 유지하거나 build.nvidia.com에서 다른 모델 슬러그로 교체
6. [ ] 저장 후 **앱 재시작** (LLM 프로바이더 변경은 재시작이 필요합니다 — TTS와 다름)

> ⚠️ NVIDIA API Trial Terms of Service 기준 **비상업적 용도**로 명시되어 있습니다. 개인 사용은 문제없으나 상업적 배포는 별도 확인 필요.
> ⚠️ 분당 요청 수 제한(약 40 RPM)이 있어 트래픽이 많으면 429 에러가 날 수 있습니다.

---

## 3. NVIDIA TTS 사용하려면 (선택 — 기본은 macOS 무료 음성 유지)

일반 API 키만으로는 안 됩니다. **Function ID**라는 값이 추가로 필요합니다.

1. [ ] https://build.nvidia.com/resembleai/chatterbox-multilingual-tts 접속
2. [ ] **Deploy** 탭에서 본인 계정 기준 코드 스니펫 확인 → 거기 적힌 `function-id` 값 복사
   (이 값은 계정마다 다를 수 있어 제가 미리 채워둘 수 없습니다)
3. [ ] 같은 페이지에서 API 키(`nvapi-...`) 발급
4. [ ] VoiceDesk → **Settings → TTS 탭** → 프로바이더 `nvidia` 선택
5. [ ] API 키, Function ID 입력. 음성은 기본값 `Chatterbox-Multilingual.ko-KR.Male` 유지(한국어 지원 확인됨)
6. [ ] 저장 — TTS는 **재시작 없이 즉시 적용**됩니다
7. [ ] 아무 명령이나 실행해서 실제로 NVIDIA 음성으로 나오는지 확인

> ⚠️ Function ID/키가 틀리거나 네트워크가 끊기면 **자동으로 macOS 로컬 음성(say)으로 폴백**하도록 만들어뒀습니다 — 무음이 되진 않지만, 폴백이 계속 발생하면 위 2번 값을 다시 확인하세요.
> ⚠️ 매 발화(대답 한 마디)마다 인터넷 왕복이 발생합니다 — 응답이 살짝 늦게 느껴질 수 있습니다.
> ℹ️ `safety/guard.py`의 "위험한 작업입니다..." 확인 음성은 아직 이 설정과 무관하게 항상 로컬 `say`를 씁니다 (범위 밖 — 필요하시면 별도로 연결 가능).

---

## 4. 기기에서 직접 확인해야 하는 것 (제가 여기서 실행할 수 없음)

- [ ] **마이크 권한**: `시스템 설정 → 개인정보 보호 및 보안 → 마이크`에서 VoiceDesk(또는 터미널) 허용
- [ ] **웨이크워드 실제 인식**:
  - "Hey Jarvis" — openwakeword 사전학습 모델, 첫 실행 시 인터넷으로 모델 자동 다운로드
  - "Hey Desk" — 연속 STT 매칭 방식, 별도 모델 다운로드 없음
  - 콘솔에 `[WakeWord] Microphone input is SILENT (0)` 경고가 뜨면 마이크 권한 문제
- [ ] **다단계 명령 실제 동작**: "크롬 열고 gmail 검색해줘" 같은 명령이 끝까지 수행되는지
- [ ] **노치 UI 실제 모양**: 특히 물리 노치가 있는 MacBook에서 텍스트가 노치에 가리지 않는지, 상태별 확장 애니메이션이 자연스러운지
- [ ] **NVIDIA TTS 실제 음질/지연**: 2·3번 설정 후 체감 속도와 발음이 만족스러운지

---

## 5. 실행 명령 (요약)

```bash
cd /Users/evan/voicedesk
pip3 install -r requirements.txt
python3 main.py
```

메뉴바 아이콘 → **Open Settings**에서 LLM/TTS 탭 확인 가능.
