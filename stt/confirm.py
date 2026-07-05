def listen_for_confirmation(duration: int = 3) -> str:
    """Record a short utterance and transcribe it — the shared voice yes/no
    capture used by the danger-confirm flow and proactive suggestions."""
    import sounddevice as sd
    import tempfile, wave, os
    from stt.macos_speech import MacOSSpeechAdapter

    sample_rate = 16000
    audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate,
                   channels=1, dtype="int16")
    sd.wait()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        with wave.open(f.name, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio.tobytes())
        tmp_path = f.name

    try:
        adapter = MacOSSpeechAdapter()
        with open(tmp_path, "rb") as af:
            return adapter.transcribe(af.read()).strip()
    finally:
        os.unlink(tmp_path)
