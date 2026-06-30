from abc import ABC, abstractmethod


class STTBase(ABC):
    @abstractmethod
    def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe audio bytes to text. Returns empty string on failure."""
        ...
