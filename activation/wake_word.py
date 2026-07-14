import re
import threading
import time

# openwakeword ships pre-trained models — arbitrary phrase strings are NOT valid
# model names. "hey_jarvis" is the closest freely available model. Phrases with
# no matching pre-trained model (e.g. "hey desk") are handled by the STT fallback
# instead, so they are intentionally absent here.
_PHRASE_TO_MODEL = {
    "hey jarvis": "hey_jarvis",
}

# The STT fallback transcribes with ko-KR, so an English wake phrase comes back
# as its Korean transliteration ("hey desk" → "헤이 데스크"). Match those too.
_PHRASE_VARIANTS = {
    "hey desk": [
        "헤이 데스크", "에이 데스크", "헤이 데스크톱", "hey desk",
        "하이 데스크", "해이 데스크", "헤이 데스",
    ],
    "hey jarvis": ["헤이 자비스", "에이 자비스", "hey jarvis"],
}

# Seconds to ignore further detections after one fires. openwakeword scores stay
# above threshold for several consecutive frames per utterance, so without this
# a single "hey jarvis" triggers a burst of activations.
_REFRACTORY_SEC = 3.0

# A healthy input stream delivers a frame every 80ms (silence still arrives as
# zero-filled frames). Receiving nothing for this long means the stream was
# starved — macOS/PortAudio permanently stops a running input stream when a
# second one opens on the same device — so the session reopens the stream.
_STARVATION_TIMEOUT_SEC = 2.0

_WORD_RE = re.compile(r"[^a-z0-9가-힣]+")


def _normalize(text: str) -> str:
    """Lowercase and collapse punctuation to single spaces for loose matching."""
    return _WORD_RE.sub(" ", text.lower()).strip()


def _resolve_targets(phrases: list[str]) -> tuple[list[str], list[str]]:
    """Split configured phrases into openwakeword models and STT-match phrases.

    Returns (model_names, stt_phrases). A phrase with a pre-trained model uses
    openwakeword; any other phrase falls back to continuous STT matching.
    """
    models: list[str] = []
    stt_phrases: list[str] = []
    for raw in phrases:
        p = raw.strip().lower()
        if not p:
            continue
        model = _PHRASE_TO_MODEL.get(p)
        if model:
            if model not in models:
                models.append(model)
        elif p not in stt_phrases:
            stt_phrases.append(p)
    return models, stt_phrases


def _phrase_matches(transcript: str, phrases: list[str]) -> bool:
    """True if any target phrase appears in the transcript (loose match).

    Also matches known transliteration variants and space-insensitive forms,
    since the ko-KR STT renders English phrases in Hangul with fuzzy spacing.
    """
    t = _normalize(transcript)
    t_tight = t.replace(" ", "")
    for p in phrases:
        if not p.strip():
            continue
        candidates = [p] + _PHRASE_VARIANTS.get(_normalize(p), [])
        for cand in candidates:
            n = _normalize(cand)
            if n and (n in t or n.replace(" ", "") in t_tight):
                return True
    return False


class WakeWordListener:
    """Listens for one or more wake phrases and invokes a callback on detection.

    Pre-trained phrases (e.g. "hey jarvis") are detected with openwakeword.
    Other phrases (e.g. "hey desk") are matched by continuously transcribing
    short utterances with the STT adapter. Both share a single microphone stream.
    """

    def __init__(self, phrase, callback, speech_amp=500, silence_frames=5):
        """
        Args:
            phrase: A wake phrase string, or a list of phrases to listen for.
            callback: Callable invoked when any wake phrase is detected.
            speech_amp: int16 mic amplitude that counts as speech, for the
                STT-fallback VAD (tune down for quiet mics/rooms, up for noisy ones).
            silence_frames: consecutive silent frames (~80ms each) that end
                an utterance for the STT-fallback VAD.
        """
        if isinstance(phrase, str):
            phrases = [phrase]
        else:
            phrases = list(phrase)
        self._phrase = phrases[0].lower() if phrases else ""
        self._phrases = phrases
        self._models, self._stt_phrases = _resolve_targets(phrases)
        self._callback = callback
        self._speech_amp = speech_amp
        self._silence_frames = silence_frames
        self._running = False
        self._thread = None
        self._stt_busy = False
        self._last_fire = 0.0
        self._pause_requested = threading.Event()
        self._stream_closed = threading.Event()
        self._stream_closed.set()
        # Makes "set pause flag" atomic against the session's "check flag then
        # mark stream open", so pause() can never slip between the two and
        # return while a stream is about to open.
        self._stream_lock = threading.Lock()

    def _fire(self) -> bool:
        """Invoke the callback unless still inside the refractory window."""
        now = time.monotonic()
        if now - self._last_fire < _REFRACTORY_SEC:
            return False
        self._last_fire = now
        self._callback()
        return True

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def pause(self, timeout: float = 3.0) -> None:
        """Close the mic stream and wait until it is actually closed.

        macOS/PortAudio permanently starves a running input stream the moment
        a second stream opens on the same device, so anything that records
        (command capture, confirmation capture) must pause the listener first
        and resume() it once the mic is free again."""
        with self._stream_lock:
            self._pause_requested.set()
        self._stream_closed.wait(timeout)

    def resume(self) -> None:
        self._pause_requested.clear()

    def _run_stt_match(self, audio_int16) -> None:
        """Transcribe a buffered utterance and fire the callback on a match."""
        import io
        import wave
        import sys
        from stt.macos_speech import MacOSSpeechAdapter

        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_int16.tobytes())
            transcript = MacOSSpeechAdapter().transcribe(buf.getvalue())
            if transcript and _phrase_matches(transcript, self._stt_phrases):
                print(f"[WakeWord] STT wake phrase matched in: '{transcript}'", file=sys.stderr)
                self._fire()
            elif transcript:
                # Logged so real mismatches (e.g. an unlisted transliteration)
                # can be diagnosed and added to _PHRASE_VARIANTS with evidence.
                print(f"[WakeWord] STT transcript did not match wake phrase: '{transcript}'", file=sys.stderr)
        except Exception as e:
            print(f"[WakeWord] STT match error: {e}", file=sys.stderr)
        finally:
            self._stt_busy = False

    def _load_model(self):
        import sys
        if not self._models:
            return None
        import openwakeword
        import openwakeword.utils
        from openwakeword.model import Model

        try:
            return Model(wakeword_models=self._models, inference_framework="onnx")
        except Exception as e:
            print(f"[WakeWord] Model load failed ({e}); downloading...", file=sys.stderr)
            try:
                openwakeword.utils.download_models()
                return Model(wakeword_models=self._models, inference_framework="onnx")
            except Exception as down_err:
                print(f"[WakeWord] Critical: could not load models: {down_err}", file=sys.stderr)
                return None

    def _listen_loop(self) -> None:
        import sys
        try:
            model = self._load_model()
            while self._running:
                if self._pause_requested.is_set():
                    time.sleep(0.05)
                    continue
                try:
                    self._stream_session(model)
                except Exception as e:
                    print(f"[WakeWord] Stream error ({e}); reopening in 1s",
                          file=sys.stderr)
                    time.sleep(1.0)
        except Exception as e:
            print(f"[WakeWord] Listener thread error: {e}", file=sys.stderr)

    def _stream_session(self, model) -> None:
        """One microphone-stream lifetime: open, consume frames, detect.

        Returns (with the stream closed) when paused, stopped, or the stream
        stops delivering frames — the caller reopens. Frames arrive via a
        callback into a queue, so a starved stream shows up as a queue timeout
        instead of blocking a read() call forever."""
        import queue
        import sys
        from collections import deque

        import numpy as np
        import sounddevice as sd

        sample_rate = 16000
        chunk = 1280  # 80ms frames
        frames: queue.Queue = queue.Queue(maxsize=64)

        def _cb(indata, _n, _t, _status):
            try:
                frames.put_nowait(indata.copy().flatten())
            except queue.Full:
                pass

        # Rolling buffer + simple energy VAD for the STT fallback path.
        buffer = deque(maxlen=int(sample_rate * 2 / chunk))  # ~2s of frames
        SPEECH_AMP = self._speech_amp      # int16 amplitude that counts as speech
        SILENCE_FRAMES = self._silence_frames  # silent frames that end an utterance
        in_speech = False
        silence_run = 0
        loop_counter = 0

        with self._stream_lock:
            if self._pause_requested.is_set():
                return
            self._stream_closed.clear()
        try:
            with sd.InputStream(
                samplerate=sample_rate, channels=1, dtype="int16",
                blocksize=chunk, callback=_cb,
            ):
                print(
                    f"[WakeWord] Listening — openwakeword={self._models}, "
                    f"stt_phrases={self._stt_phrases}",
                    file=sys.stderr,
                )
                while self._running and not self._pause_requested.is_set():
                    try:
                        flat = frames.get(timeout=_STARVATION_TIMEOUT_SEC)
                    except queue.Empty:
                        print("[WakeWord] Mic stream stopped delivering audio; reopening.",
                              file=sys.stderr)
                        return
                    max_amp = int(np.abs(flat).max())

                    loop_counter += 1
                    if loop_counter % 13 == 0 and max_amp == 0:
                        print(
                            "[WakeWord] Microphone input is SILENT (0). Check macOS "
                            "Settings → Privacy & Security → Microphone for VoiceDesk.",
                            file=sys.stderr,
                        )

                    # --- openwakeword path ---
                    if model is not None:
                        prediction = model.predict(flat)
                        for name, score in prediction.items():
                            if score > 0.5:
                                print(f"[WakeWord] '{name}' detected (score {score:.2f})", file=sys.stderr)
                                if self._fire():
                                    try:
                                        model.reset()
                                    except Exception:
                                        pass
                                break

                    # --- STT literal-match path ---
                    if self._stt_phrases:
                        buffer.append(flat)
                        if max_amp >= SPEECH_AMP:
                            in_speech = True
                            silence_run = 0
                        elif in_speech:
                            silence_run += 1
                            if silence_run >= SILENCE_FRAMES and not self._stt_busy:
                                self._stt_busy = True
                                utterance = np.concatenate(list(buffer))
                                buffer.clear()
                                in_speech = False
                                silence_run = 0
                                threading.Thread(
                                    target=self._run_stt_match,
                                    args=(utterance,),
                                    daemon=True,
                                ).start()
        finally:
            self._stream_closed.set()


# The process-wide listener that pause_listening()/resume_listening() control.
# Registered by main() so every other microphone consumer (command recording,
# confirmation capture) can pause the wake stream instead of silently killing
# it by opening a second stream on the same device.
_active_listener = None


def set_active_listener(listener) -> None:
    global _active_listener
    _active_listener = listener


def pause_listening() -> None:
    if _active_listener is not None:
        _active_listener.pause()


def resume_listening() -> None:
    if _active_listener is not None:
        _active_listener.resume()
