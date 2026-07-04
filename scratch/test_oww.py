import openwakeword
from openwakeword.model import Model
import numpy as np

# 모델 로드
model = Model(wakeword_models=['hey_jarvis'], inference_framework='onnx')

# 임의의 int16 데이터 생성
data_int16 = np.random.randint(-32768, 32767, size=1280, dtype=np.int16)
try:
    pred_int16 = model.predict(data_int16)
    print("int16 입력 테스트 결과:", pred_int16)
except Exception as e:
    print("int16 입력 에러:", e)

# 임의의 float32 데이터 생성 (-1.0 ~ 1.0)
data_float32 = np.random.uniform(-1.0, 1.0, size=1280).astype(np.float32)
try:
    pred_float32 = model.predict(data_float32)
    print("float32 입력 테스트 결과:", pred_float32)
except Exception as e:
    print("float32 입력 에러:", e)
