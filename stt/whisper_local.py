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

# no_speech_prob answers "was this even speech?"; avg_logprob answers "how
# sure am I of the WORDS?". Unclear-but-real speech passes the first gate
# and still comes out as a confident-looking mis-hearing ("혐의날 열어로서")
# that the agent then acts on — opening some app the user never asked for.
#
# The confidence decision is made for the UTTERANCE as a whole
# (length-weighted mean), never per segment: dropping individual segments
# silently truncates the middle of real commands, and short Korean commands
# on the base model routinely score between -0.8 and -1.2 even when heard
# correctly — a tighter per-segment floor made the assistant "stop hearing"
# ordinary speech.
_MIN_AVG_LOGPROB = -1.2

# Bias decoding toward the vocabulary actually spoken at this assistant —
# app/site names Whisper otherwise mangles ("아이텀" → "아이템 2",
# "크롬" → "그럼"). Applied per-utterance; VAD, the no-speech gate, and the
# confidence floor keep it from stamping these words onto silence.
_INITIAL_PROMPT = (
    "크롬 열어줘. 사파리 열어줘. 아이텀 열어줘. 터미널 열어줘. "
    "파인더 열어줘. 브이에스코드 열어줘. 유튜브 틀어줘. 지메일 열어줘. "
    "네이버 열어줘. 구글에서 검색해줘. 확인 버튼 눌러줘. 클로드 실행해줘."
)


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
                initial_prompt=_INITIAL_PROMPT,
            )
            kept = []
            for seg in segments:
                # no_speech_prob close to 1.0 means the model itself doesn't
                # think this segment contains speech — drop it rather than
                # keep whatever garbage text it emitted anyway.
                if seg.no_speech_prob > 0.6:
                    continue
                kept.append(seg)
            if not kept:
                return ""
            total_chars = sum(len(seg.text) for seg in kept) or 1
            weighted_logprob = sum(
                seg.avg_logprob * len(seg.text) for seg in kept
            ) / total_chars
            if weighted_logprob < _MIN_AVG_LOGPROB:
                return ""
            text = "".join(seg.text for seg in kept).strip()
            if not _HAS_WORD_CHAR.search(text):
                return ""
            return text
        except Exception:
            return ""
        finally:
            os.unlink(tmp_path)
