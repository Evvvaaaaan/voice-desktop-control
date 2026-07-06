# main.py
import io
import os
import sys
import threading
import wave

def _pre_load_portaudio() -> None:
    """Extract and load libportaudio.dylib from python314.zip if inside an app bundle, and patch paths."""
    import zipfile
    import tempfile
    import types

    zip_path = None
    for p in sys.path:
        if p.endswith(".zip") and os.path.exists(p):
            zip_path = p
            break

    if not zip_path:
        return

    try:
        tmp_dir = tempfile.gettempdir()
        dest_dir = os.path.join(tmp_dir, "portaudio-binaries")
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, "libportaudio.dylib")

        with zipfile.ZipFile(zip_path, 'r') as z:
            dylib_names = [name for name in z.namelist() if "libportaudio.dylib" in name]
            if dylib_names:
                dylib_data = z.read(dylib_names[0])
                with open(dest_path, "wb") as f:
                    f.write(dylib_data)

        # Inject mock module to intercept sounddevice's internal _sounddevice_data lookup
        dummy_mod = types.ModuleType("_sounddevice_data")
        dummy_mod.__path__ = [tmp_dir]
        sys.modules["_sounddevice_data"] = dummy_mod
        
        print(f"[Sounddevice] Patched _sounddevice_data.__path__ to {tmp_dir} with dylib in {dest_path}")
    except Exception as e:
        print(f"[Sounddevice] Pre-loading & patching PortAudio failed: {e}")


from config.loader import Config, load_config, save_config
from stt import get_stt_adapter
from llm import get_llm_adapter
from safety.guard import SafetyGuard
from metrics.collector import MetricsCollector
from routines.detector import RoutineDetector
from routines.manager import RoutineManager
from activation.hotkey import HotkeyListener
from activation.wake_word import WakeWordListener
from agent.core import Agent
from memory.store import MemoryStore
from memory.embedder import get_embedder
from memory.retriever import MemoryRetriever
from memory.summarizer import DailySummarizer
from memory.suggester import SuggestionEngine
from ui.notch_hud import NotchHUD
from ui.menubar import VoiceDeskMenuBar
from ui.settings.window import SettingsWindow

APP_NAME = "VoiceDesk"


def _default_state_dir() -> str:
    override = os.environ.get("VOICEDESK_HOME")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", APP_NAME
        )
    return os.path.join(os.path.expanduser("~"), ".voicedesk")


def _project_config_path() -> str | None:
    """In a dev run (`python3 main.py` from the repo checkout), prefer the
    repo's own config.yaml over the per-user copy in STATE_DIR — otherwise
    edits to it silently do nothing: the first run seeds STATE_DIR's
    config.yaml from Config() defaults, and every run after that reads and
    (via the Settings UI) writes that copy instead, never the repo file.

    The packaged .app (py2app sets sys.frozen) always keeps using STATE_DIR:
    its bundled config.yaml lives inside the app bundle, which must stay
    read-only/untouched (settings belong in Application Support, not in a
    signed bundle)."""
    if getattr(sys, "frozen", False):
        return None
    candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    return candidate if os.path.exists(candidate) else None


STATE_DIR = _default_state_dir()
CONFIG_PATH = (
    os.environ.get("VOICEDESK_CONFIG")
    or _project_config_path()
    or os.path.join(STATE_DIR, "config.yaml")
)
DB_PATH = os.environ.get("VOICEDESK_DB", os.path.join(STATE_DIR, "command_history.db"))
ROUTINES_PATH = os.environ.get("VOICEDESK_ROUTINES", os.path.join(STATE_DIR, "routines.json"))


def _sync_runtime_env() -> None:
    os.environ["VOICEDESK_CONFIG"] = CONFIG_PATH
    os.environ["VOICEDESK_DB"] = DB_PATH
    os.environ["VOICEDESK_ROUTINES"] = ROUTINES_PATH


def _wav_bytes(audio, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16 = 2 bytes per sample
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()


def record_audio(duration: int = 5, sample_rate: int = 16000, on_level=None,
                 stop_on_silence: bool = False,
                 no_speech_timeout: float | None = None) -> bytes:
    """Record audio from the microphone and return WAV bytes (16kHz, mono, int16).

    When `on_level` is given, records via a streaming InputStream and calls
    `on_level(rms)` (~10x/sec, rms normalized to 0..1) as audio arrives, for a
    live level meter. When omitted, behavior is unchanged (sd.rec + sd.wait).

    With `stop_on_silence` (streaming path only), `duration` acts as a maximum:
    recording ends early once speech has been heard and is followed by ~1.2s of
    silence, so short commands don't wait out the full window and long commands
    aren't cut mid-sentence (pass a larger `duration`). `no_speech_timeout`
    additionally ends the recording if speech hasn't STARTED within that many
    seconds — used by follow-up listening so silence returns to idle quickly.
    """
    import sounddevice as sd

    if on_level is None:
        audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate,
                       channels=1, dtype="int16")
        sd.wait()
        return _wav_bytes(audio, sample_rate)

    import numpy as np

    frames = []
    blocksize = int(sample_rate * 0.1)  # ~100ms per callback
    done = threading.Event()
    SPEECH_AMP = 500           # int16 amplitude that counts as speech
    SILENCE_BLOCKS = 12        # ~1.2s of trailing silence ends the utterance
    vad = {"in_speech": False, "silence_run": 0, "blocks": 0}

    def _cb(indata, _n, _t, _status):
        frames.append(indata.copy())
        try:
            rms = float(np.sqrt(np.mean(indata.astype("float32") ** 2)))
            on_level(min(rms / 3000.0, 1.0))  # int16 rms → ~0..1
        except Exception:
            pass
        if not stop_on_silence:
            return
        try:
            vad["blocks"] += 1
            if int(np.abs(indata).max()) >= SPEECH_AMP:
                vad["in_speech"] = True
                vad["silence_run"] = 0
            elif vad["in_speech"]:
                vad["silence_run"] += 1
                if vad["silence_run"] >= SILENCE_BLOCKS:
                    done.set()
            elif (no_speech_timeout is not None
                    and vad["blocks"] * 0.1 >= no_speech_timeout):
                done.set()
        except Exception:
            pass

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16",
                        blocksize=blocksize, callback=_cb):
        if stop_on_silence:
            elapsed_ms = 0
            while elapsed_ms < duration * 1000 and not done.is_set():
                sd.sleep(100)
                elapsed_ms += 100
        else:
            sd.sleep(int(duration * 1000))

    audio = np.concatenate(frames) if frames else np.zeros((0, 1), dtype="int16")
    return _wav_bytes(audio, sample_rate)


def _provider_info(cfg):
    """(stt, llm, llm_model, tts, tts_voice) for the notch provider panel."""
    llm_model = {
        "claude": cfg.llm.claude_model,
        "openai": cfg.llm.openai_model,
        "nvidia": cfg.llm.nvidia_model,
    }.get(cfg.llm.provider, cfg.llm.ollama_model)
    return (cfg.stt.provider, cfg.llm.provider, llm_model, "macos", cfg.tts.voice)


def _ensure_data_dir():
    for path in (CONFIG_PATH, DB_PATH, ROUTINES_PATH):
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        save_config(Config(), CONFIG_PATH)


# One command at a time: a second hotkey press / duplicate wake-word fire while
# a command is being recorded or executed must not start an overlapping session.
_COMMAND_LOCK = threading.Lock()
# An activation that arrives while a command is still running is remembered
# here instead of being dropped, and listening restarts as soon as the current
# command finishes — so back-to-back voice commands don't lose the last one.
_PENDING_ACTIVATION = threading.Event()


def _record_command(agent: Agent, hud: NotchHUD, stt_adapter,
                    follow_up: bool = False) -> None:
    if not _COMMAND_LOCK.acquire(blocking=False):
        _PENDING_ACTIVATION.set()
        return
    try:
        first = True
        while True:
            hud.set_state("listening")
            # Follow-up rounds stop quickly when the user stays silent.
            audio_bytes = record_audio(
                duration=10, on_level=hud.update_mic_level, stop_on_silence=True,
                no_speech_timeout=None if first else 5.0,
            )

            hud.set_state("processing")
            command = stt_adapter.transcribe(audio_bytes)
            if not command.strip():
                hud.set_state("idle")
                return
            hud.set_transcript(command)

            hud.set_state("executing")
            result = agent.run(command)
            failed = (not result or result == "취소됨"
                      or result.startswith(("error", "오류")))
            hud.set_state("error" if failed else "success")
            if failed or not follow_up:
                return
            # Continuous mode: brief success display, then listen again
            # without requiring the wake word.
            import time
            time.sleep(1.5)
            hud.set_transcript("")
            first = False
    except Exception as e:
        # A dead thread would leave the HUD stuck in its last state forever.
        import sys
        import traceback
        print(f"[Command] Unhandled error: {e}", file=sys.stderr)
        traceback.print_exc()
        try:
            hud.set_state("error")
            from actions.tts import speak
            speak("오류가 발생했어요. 로그를 확인해 주세요.")
        except Exception:
            pass
    finally:
        import time
        time.sleep(1.5)
        hud.set_transcript("")
        hud.set_state("idle")
        _COMMAND_LOCK.release()
        # The user tried to speak while this command was running — start
        # listening again right away so that command isn't lost.
        if _PENDING_ACTIVATION.is_set():
            _PENDING_ACTIVATION.clear()
            threading.Thread(
                target=_record_command, args=(agent, hud, stt_adapter),
                kwargs={"follow_up": follow_up}, daemon=True,
            ).start()


def main():
    _pre_load_portaudio()
    _sync_runtime_env()
    _ensure_data_dir()
    config = load_config(CONFIG_PATH)

    stt = get_stt_adapter(config)
    llm = get_llm_adapter(config)
    collector = MetricsCollector(DB_PATH)
    detector = RoutineDetector(DB_PATH)
    manager = RoutineManager(ROUTINES_PATH)  # noqa: F841  initialises routines.json

    hud = NotchHUD()
    hud.set_widgets(config.hud.show_clock, config.hud.show_media, config.hud.show_battery,
                    config.hud.hover_to_expand, config.hud.interaction_sounds)
    from agent import tools as agent_tools
    agent_tools.set_text_input_provider(hud.request_text_input)
    guard = SafetyGuard(require_confirmation=config.safety.require_confirmation,
                        ui_confirm=hud.arm_danger_prompt)
    hud.show()
    hud.set_state("idle")
    hud.set_provider_info(*_provider_info(config))

    memory_store = None
    if config.memory.enabled:
        try:
            memory_store = MemoryStore(DB_PATH)
        except Exception as e:
            print(f"[Memory] store init failed ({e}); memory disabled.", file=sys.stderr)
    embedder = get_embedder(config)
    retriever = (MemoryRetriever(memory_store, embedder, top_k=config.memory.retrieval_top_k)
                 if memory_store else None)

    agent = Agent(llm, guard, collector, detector, config.tts,
                  on_state=hud.set_state, memory=memory_store, retriever=retriever)

    if memory_store:
        DailySummarizer(memory_store, llm, embedder).start_background()

    def _try_begin_session() -> bool:
        return _COMMAND_LOCK.acquire(blocking=False)

    def _end_session() -> None:
        _COMMAND_LOCK.release()
        # The user tried to speak during the suggestion — replay it, same as
        # _record_command's finally block.
        if _PENDING_ACTIVATION.is_set():
            _PENDING_ACTIVATION.clear()
            threading.Thread(
                target=_record_command, args=(agent, hud, stt),
                kwargs={"follow_up": config.activation.continuous}, daemon=True,
            ).start()

    def _run_suggested(command: str) -> None:
        # The suggestion session already holds _COMMAND_LOCK; mirror
        # _record_command's executing tail minus recording/lock.
        hud.set_transcript(command)
        hud.set_state("executing")
        result = agent.run(command)
        failed = (not result or result == "취소됨"
                  or result.startswith(("error", "오류")))
        hud.set_state("error" if failed else "success")
        import time
        time.sleep(1.5)
        hud.set_transcript("")
        hud.set_state("idle")

    if memory_store and config.suggestion.enabled:
        from actions.tts import speak as _suggest_speak
        SuggestionEngine(
            memory_store, config.suggestion,
            speak_fn=lambda text: _suggest_speak(
                text, config.tts.voice, config.tts.rate, tts_config=config.tts),
            run_command_fn=_run_suggested,
            begin_session=_try_begin_session, end_session=_end_session,
            hud=hud,
        ).start_background()

    def on_activation():
        t = threading.Thread(
            target=_record_command, args=(agent, hud, stt),
            kwargs={"follow_up": config.activation.continuous}, daemon=True,
        )
        t.start()

    def on_config_change(new_config):
        nonlocal stt, llm, config
        config = new_config
        stt = get_stt_adapter(new_config)
        llm = get_llm_adapter(new_config)
        agent.set_llm(llm)
        if memory_store:
            agent.set_retriever(MemoryRetriever(
                memory_store, get_embedder(new_config),
                top_k=new_config.memory.retrieval_top_k))
        hud.set_provider_info(*_provider_info(new_config))
        hud.set_widgets(new_config.hud.show_clock, new_config.hud.show_media,
                        new_config.hud.show_battery, new_config.hud.hover_to_expand,
                        new_config.hud.interaction_sounds)

    settings_window = SettingsWindow(
        config, CONFIG_PATH, on_config_change,
        routines_path=ROUTINES_PATH, db_path=DB_PATH,
    )
    hud.set_open_settings_callback(settings_window.show)

    if config.activation.hotkey:
        hotkey = HotkeyListener(config.activation.hotkey_binding, on_activation)
        hotkey.start()

    if config.activation.wake_word:
        # Listen for both the configured phrase and "hey jarvis" so the reliable
        # pre-trained model works alongside the user's chosen phrase.
        phrases = [config.activation.wake_phrase, "hey jarvis"]
        wakeword = WakeWordListener(phrases, on_activation)
        wakeword.start()

    app = VoiceDeskMenuBar(agent, hud, settings_window, on_activation_callback=on_activation)
    app.run()


if __name__ == "__main__":
    main()
