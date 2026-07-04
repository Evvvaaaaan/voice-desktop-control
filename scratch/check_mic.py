import sounddevice as sd
import numpy as np
import time

print("=== 마이크 장치 목록 ===")
devices = sd.query_devices()
print(devices)

default_input = sd.query_devices(kind='input')
print("\n기본 입력 장치:", default_input['name'])

print("\n3초 동안 마이크 입력을 진단합니다. 소리를 내어 주세요...")
audio_data = []

def callback(indata, frames, time_info, status):
    if status:
        print("Status:", status)
    # 볼륨 에너지 계산
    volume_norm = np.linalg.norm(indata) * 10
    audio_data.append(volume_norm)
    # 간단한 볼륨 게이지 시각화
    gauge = "#" * int(min(volume_norm, 50))
    print(f"Volume: {volume_norm:6.2f} {gauge}")

try:
    with sd.InputStream(callback=callback, channels=1, samplerate=16000, dtype='int16'):
        time.sleep(3)
except Exception as e:
    print("에러 발생:", e)

if audio_data:
    avg_vol = sum(audio_data) / len(audio_data)
    print(f"\n평균 볼륨 수준: {avg_vol:.2f}")
    if avg_vol < 0.1:
        print("⚠️ 경고: 입력된 사운드가 거의 없습니다. 마이크 권한이 차단되었거나 음소거 상태일 수 있습니다.")
    else:
        print("✅ 마이크 신호가 정상적으로 수신되고 있습니다.")
else:
    print("⚠️ 경고: 오디오 입력 스트림이 시작되지 못했습니다.")
