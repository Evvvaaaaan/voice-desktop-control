# stt/macos_speech.py
import tempfile
import os
import threading
from stt.base import STTBase

try:
    from Speech import (
        SFSpeechRecognizer,
        SFSpeechURLRecognitionRequest,
        SFSpeechRecognizerAuthorizationStatusAuthorized,
    )
    from Foundation import NSURL, NSLocale, NSBundle
except ImportError:
    SFSpeechRecognizer = None


def _bundle_has_speech_usage_description() -> bool:
    """SFSpeechRecognizer aborts the process (SIGABRT) if the running
    bundle's Info.plist has no NSSpeechRecognitionUsageDescription key.
    The packaged .app declares it (see setup.py); a bare `python3 main.py`
    dev run is hosted by the interpreter's own bundle, which doesn't — so
    that path must fall back instead of touching the Speech framework."""
    try:
        info = NSBundle.mainBundle().infoDictionary()
        return bool(info and info.get("NSSpeechRecognitionUsageDescription"))
    except Exception:
        return False


class MacOSSpeechAdapter(STTBase):
    """Native macOS Speech framework, on-device where the locale supports it
    — no per-utterance network round-trip. Falls back to the Google Web
    Speech API (via `speech_recognition`) when the Speech framework isn't
    usable (missing pyobjc-framework-Speech, or unbundled dev run)."""

    _auth_status = None

    def transcribe(self, audio_bytes: bytes) -> str:
        if SFSpeechRecognizer is None or not _bundle_has_speech_usage_description():
            return self._transcribe_fallback(audio_bytes)

        if not self._ensure_authorized():
            print("[STT] Error: speech recognition not authorized")
            return ""

        recognizer = SFSpeechRecognizer.alloc().initWithLocale_(
            NSLocale.alloc().initWithLocaleIdentifier_("ko-KR")
        )
        if recognizer is None or not recognizer.isAvailable():
            print("[STT] Error: macOS speech recognizer unavailable for ko-KR")
            return ""

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            request = SFSpeechURLRecognitionRequest.alloc().initWithURL_(
                NSURL.fileURLWithPath_(tmp_path)
            )
            if recognizer.supportsOnDeviceRecognition():
                request.setRequiresOnDeviceRecognition_(True)

            result_holder = {"text": "", "error": None}
            done = threading.Event()

            def _handler(result, error):
                if error is not None:
                    result_holder["error"] = error
                    done.set()
                    return
                if result is not None and result.isFinal():
                    result_holder["text"] = result.bestTranscription().formattedString()
                    done.set()

            recognizer.recognitionTaskWithRequest_resultHandler_(request, _handler)
            if not done.wait(timeout=15):
                print("[STT] Transcription failed: timed out")
                return ""
            if result_holder["error"] is not None:
                print(f"[STT] Transcription failed: {result_holder['error']}")
                return ""
            return result_holder["text"].strip()
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    @classmethod
    def _ensure_authorized(cls) -> bool:
        if cls._auth_status is None:
            cls._auth_status = SFSpeechRecognizer.authorizationStatus()
        if cls._auth_status == SFSpeechRecognizerAuthorizationStatusAuthorized:
            return True

        done = threading.Event()
        result = {}

        def _cb(status):
            result["status"] = status
            done.set()

        SFSpeechRecognizer.requestAuthorization_(_cb)
        done.wait(timeout=30)
        cls._auth_status = result.get("status", cls._auth_status)
        return cls._auth_status == SFSpeechRecognizerAuthorizationStatusAuthorized

    def _transcribe_fallback(self, audio_bytes: bytes) -> str:
        try:
            import speech_recognition as sr
        except ImportError:
            print("[STT] Error: speech_recognition library is missing!")
            return ""

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            r = sr.Recognizer()
            with sr.AudioFile(tmp_path) as source:
                audio = r.record(source)
            text = r.recognize_google(audio, language="ko-KR")
            return text.strip()
        except Exception as e:
            print(f"[STT] Transcription failed: {e}")
            return ""
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
