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


def speak(text: str, voice: str = "Yuna", rate: int = 200) -> None:
    """Speak `text` aloud via the local macOS `say` command."""
    _speak_macos_safe(text, voice, rate)
