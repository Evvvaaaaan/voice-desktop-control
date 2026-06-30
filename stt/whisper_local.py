import tempfile
import os
import numpy as np
from faster_whisper import WhisperModel
from stt.base import STTBase


class WhisperLocalAdapter(STTBase):
    def __init__(self, model_size: str = "base"):
        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            segments, _ = self._model.transcribe(tmp_path, language="ko")
            return "".join(seg.text for seg in segments).strip()
        except Exception:
            return ""
        finally:
            os.unlink(tmp_path)
