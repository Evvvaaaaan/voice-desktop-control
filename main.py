# main.py
import io
import os
import threading
import wave

from config.loader import load_config
from stt import get_stt_adapter
from llm import get_llm_adapter
from safety.guard import SafetyGuard
from metrics.collector import MetricsCollector
from routines.detector import RoutineDetector
from routines.manager import RoutineManager
from activation.hotkey import HotkeyListener
from activation.wake_word import WakeWordListener
from agent.core import Agent
from ui.notch_hud import NotchHUD
from ui.menubar import VoiceDeskMenuBar
from ui.settings.window import SettingsWindow

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "command_history.db")
ROUTINES_PATH = os.path.join(os.path.dirname(__file__), "data", "routines.json")


def record_audio(duration: int = 5, sample_rate: int = 16000) -> bytes:
    """Record audio from the microphone and return WAV bytes (16kHz, mono, int16)."""
    import sounddevice as sd

    audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate,
                   channels=1, dtype="int16")
    sd.wait()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16 = 2 bytes per sample
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()


def _ensure_data_dir():
    os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)


def _record_command(agent: Agent, hud: NotchHUD, stt_adapter) -> None:
    hud.set_state("listening")
    audio_bytes = record_audio()

    hud.set_state("processing")
    command = stt_adapter.transcribe(audio_bytes)
    if not command.strip():
        hud.set_state("idle")
        return

    hud.set_state("executing")
    result = agent.run(command)
    hud.set_state("success" if result != "취소됨" else "error")

    import time
    time.sleep(1.5)
    hud.set_state("idle")


def main():
    _ensure_data_dir()
    config = load_config(CONFIG_PATH)

    stt = get_stt_adapter(config)
    llm = get_llm_adapter(config)
    guard = SafetyGuard(require_confirmation=config.safety.require_confirmation)
    collector = MetricsCollector(DB_PATH)
    detector = RoutineDetector(DB_PATH)
    manager = RoutineManager(ROUTINES_PATH)  # noqa: F841  initialises routines.json

    hud = NotchHUD()
    hud.show()
    hud.set_state("idle")

    agent = Agent(llm, guard, collector, detector, config.tts)

    def on_activation():
        t = threading.Thread(target=_record_command, args=(agent, hud, stt), daemon=True)
        t.start()

    def on_config_change(new_config):
        nonlocal stt, llm
        stt = get_stt_adapter(new_config)
        llm = get_llm_adapter(new_config)

    settings_window = SettingsWindow(
        config, CONFIG_PATH, on_config_change,
        routines_path=ROUTINES_PATH, db_path=DB_PATH,
    )

    if config.activation.hotkey:
        hotkey = HotkeyListener(config.activation.hotkey_binding, on_activation)
        hotkey.start()

    if config.activation.wake_word:
        wakeword = WakeWordListener(config.activation.wake_phrase, on_activation)
        wakeword.start()

    app = VoiceDeskMenuBar(agent, hud, settings_window)
    app.run()


if __name__ == "__main__":
    main()
