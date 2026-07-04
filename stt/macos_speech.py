# stt/macos_speech.py
import tempfile
import os
from stt.base import STTBase


class MacOSSpeechAdapter(STTBase):
    def transcribe(self, audio_bytes: bytes) -> str:
        try:
            import speech_recognition as sr
        except ImportError:
            print("[STT] Error: speech_recognition library is missing!")
            return ""

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            r = sr.Recognizer()
            with sr.AudioFile(tmp_path) as source:
                audio = r.record(source)
            text = r.recognize_google(audio, language="ko-KR")
            return text.strip()
        except Exception as e:
            print(f"[STT] Transcription failed: {e}")
            return ""
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
