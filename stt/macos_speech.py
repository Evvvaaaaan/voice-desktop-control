import subprocess
import tempfile
import os
from stt.base import STTBase


class MacOSSpeechAdapter(STTBase):
    def transcribe(self, audio_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            result = subprocess.run(
                ["python3", "-c",
                 f"import speech_recognition as sr; r=sr.Recognizer(); "
                 f"af=sr.AudioFile('{tmp_path}'); audio=r.record(af); "
                 f"print(r.recognize_google(audio, language='ko-KR'))"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip()
        except Exception:
            return ""
        finally:
            os.unlink(tmp_path)
