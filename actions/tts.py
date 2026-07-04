import subprocess
import sys


def _speak_macos(text: str, voice: str, rate: int) -> None:
    subprocess.run(["say", "-v", voice, "-r", str(rate), text], check=True)


def _speak_macos_safe(text: str, voice: str, rate: int) -> None:
    """Never raise: a missing voice or broken `say` must not kill the agent."""
    try:
        _speak_macos(text, voice, rate)
    except Exception as e:
        print(f"[TTS] say -v {voice} failed ({e}); retrying with default voice.", file=sys.stderr)
        try:
            subprocess.run(["say", "-r", str(rate), text], check=True)
        except Exception as e2:
            print(f"[TTS] say failed entirely ({e2}); giving up on speech.", file=sys.stderr)


def _speak_nvidia(text: str, tts_config) -> None:
    """Synthesize speech via NVIDIA's hosted Riva TTS NIM (gRPC) and play it back."""
    import riva.client
    import numpy as np
    import sounddevice as sd

    sample_rate = 22050
    auth = riva.client.Auth(
        use_ssl=True,
        uri="grpc.nvcf.nvidia.com:443",
        metadata_args=[
            ["function-id", tts_config.nvidia_function_id],
            ["authorization", f"Bearer {tts_config.nvidia_api_key}"],
        ],
    )
    service = riva.client.SpeechSynthesisService(auth)
    resp = service.synthesize(
        text=text,
        voice_name=tts_config.nvidia_voice,
        language_code=tts_config.nvidia_language_code,
        encoding=riva.client.AudioEncoding.LINEAR_PCM,
        sample_rate_hz=sample_rate,
    )
    audio = np.frombuffer(resp.audio, dtype=np.int16)
    sd.play(audio, sample_rate)
    sd.wait()


def speak(text: str, voice: str = "Yuna", rate: int = 200, tts_config=None) -> None:
    """Speak `text` aloud.

    `tts_config` (a config.loader.TTSConfig) selects the provider. When absent
    or provider is "macos", falls back to the local `say` command using
    `voice`/`rate` directly — this keeps existing call sites unchanged.
    """
    if tts_config is not None and getattr(tts_config, "provider", "macos") == "nvidia":
        try:
            _speak_nvidia(text, tts_config)
            return
        except Exception as e:
            print(f"[TTS] NVIDIA synthesis failed ({e}); falling back to local voice.", file=sys.stderr)
    _speak_macos_safe(text, voice, rate)
