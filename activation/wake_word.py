import threading

# Maps user-facing phrase to the closest available openwakeword model name.
# openwakeword ships pre-trained models — arbitrary phrase strings are not valid
# model names.  "hey_jarvis" is the closest freely available model.
_PHRASE_TO_MODEL = {
    "hey desk": "hey_jarvis",
    "hey jarvis": "hey_jarvis",
}


class WakeWordListener:
    """Listens for wake word detection and invokes a callback."""

    def __init__(self, phrase: str, callback):
        """
        Initialize wake word listener.

        Args:
            phrase: Wake word phrase to listen for (e.g. "hey desk")
            callback: Callable to invoke when wake word is detected
        """
        self._phrase = phrase.lower()
        self._callback = callback
        self._running = False
        self._thread = None

    def start(self) -> None:
        """Start listening for the wake word."""
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop listening for the wake word."""
        self._running = False

    def _listen_loop(self) -> None:
        """Main listen loop using openwakeword for wake word detection."""
        try:
            from openwakeword.model import Model
            import sounddevice as sd

            model_name = _PHRASE_TO_MODEL.get(self._phrase, "hey_jarvis")
            model = Model(wakeword_models=[model_name], inference_framework="onnx")
            sample_rate = 16000
            chunk = 1280

            with sd.InputStream(
                samplerate=sample_rate, channels=1, dtype="int16", blocksize=chunk
            ) as stream:
                while self._running:
                    audio_chunk, _ = stream.read(chunk)
                    prediction = model.predict(audio_chunk.flatten())
                    for score in prediction.values():
                        if score > 0.5:
                            self._callback()
                            break
        except Exception:
            pass
