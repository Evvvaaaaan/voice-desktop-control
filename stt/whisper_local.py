import re
import tempfile
import os
from faster_whisper import WhisperModel
from stt.base import STTBase

# Whisper is prone to hallucinating short garbage (repeated "?", "...", stray
# punctuation) on silence/background-noise-only audio when there's no real
# speech. A result containing no actual letters/digits is such a hallucination,
# not a command — treat it the same as empty so it doesn't get searched/typed.
_HAS_WORD_CHAR = re.compile(r"[A-Za-z0-9가-힣]")


class WhisperLocalAdapter(STTBase):
    def __init__(self, model_size: str = "base"):
        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            segments, _ = self._model.transcribe(
                tmp_path, language="ko",
                # Skip non-speech stretches instead of forcing a transcript
                # out of them — the single biggest source of hallucination.
                vad_filter=True,
                # Each segment repeating on the last one's (possibly
                # hallucinated) text is how hallucinations cascade/repeat.
                condition_on_previous_text=False,
            )
            parts = []
            for seg in segments:
                # no_speech_prob close to 1.0 means the model itself doesn't
                # think this segment contains speech — drop it rather than
                # keep whatever garbage text it emitted anyway.
                if seg.no_speech_prob > 0.6:
                    continue
                parts.append(seg.text)
            text = "".join(parts).strip()
            if not _HAS_WORD_CHAR.search(text):
                return ""
            return text
        except Exception:
            return ""
        finally:
            os.unlink(tmp_path)
