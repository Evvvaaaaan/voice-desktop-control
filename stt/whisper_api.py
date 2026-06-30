import tempfile
import os
from openai import OpenAI
from stt.base import STTBase


class WhisperAPIAdapter(STTBase):
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def transcribe(self, audio_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            client = self._get_client()
            with open(tmp_path, "rb") as audio_file:
                result = client.audio.transcriptions.create(
                    model="whisper-1", file=audio_file
                )
            return result.text
        except Exception:
            return ""
        finally:
            os.unlink(tmp_path)
