import pytest
from unittest.mock import patch, MagicMock
from config.loader import Config, STTConfig
from stt import get_stt_adapter
from stt.base import STTBase


def test_get_adapter_returns_base(default_config_dict, tmp_path):
    import yaml
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(default_config_dict))
    from config.loader import load_config
    config = load_config(str(cfg_file))
    adapter = get_stt_adapter(config)
    assert isinstance(adapter, STTBase)


def test_macos_adapter_calls_speech_recognition():
    """Outside a bundle with NSSpeechRecognitionUsageDescription (e.g. plain
    `python3 main.py`, or here in pytest), the adapter must not touch the
    Speech framework and instead falls back to Google Web Speech."""
    from stt.macos_speech import MacOSSpeechAdapter
    adapter = MacOSSpeechAdapter()

    with patch("speech_recognition.Recognizer") as mock_rec_cls, \
         patch("speech_recognition.AudioFile") as mock_audio_cls:

        mock_rec = mock_rec_cls.return_value
        mock_rec.recognize_google.return_value = "카카오 열어줘"

        result = adapter.transcribe(b"fake_audio")

    assert result == "카카오 열어줘"


def test_macos_adapter_uses_native_speech_framework_when_bundled(mocker):
    """Inside the packaged .app, the bundle's Info.plist declares
    NSSpeechRecognitionUsageDescription, so the adapter must use the native
    on-device SFSpeechRecognizer instead of calling out to Google."""
    from stt import macos_speech

    mocker.patch.object(macos_speech, "_bundle_has_speech_usage_description", return_value=True)
    mock_recognizer_cls = mocker.patch.object(macos_speech, "SFSpeechRecognizer")
    mocker.patch.object(macos_speech, "SFSpeechRecognizerAuthorizationStatusAuthorized", "authorized")
    mocker.patch.object(macos_speech, "NSLocale")
    mocker.patch.object(macos_speech, "NSURL")
    mock_request_cls = mocker.patch.object(macos_speech, "SFSpeechURLRecognitionRequest")

    mock_recognizer_cls.authorizationStatus.return_value = "authorized"
    mock_recognizer = mock_recognizer_cls.alloc.return_value.initWithLocale_.return_value
    mock_recognizer.isAvailable.return_value = True
    mock_recognizer.supportsOnDeviceRecognition.return_value = True

    mock_result = MagicMock()
    mock_result.isFinal.return_value = True
    mock_result.bestTranscription.return_value.formattedString.return_value = "카카오 열어줘"

    def _fake_task(request, handler):
        handler(mock_result, None)

    mock_recognizer.recognitionTaskWithRequest_resultHandler_.side_effect = _fake_task

    adapter = macos_speech.MacOSSpeechAdapter()
    adapter._auth_status = None
    result = adapter.transcribe(b"fake_audio")

    assert result == "카카오 열어줘"
    mock_request_cls.alloc.return_value.initWithURL_.return_value.setRequiresOnDeviceRecognition_.assert_called_once_with(True)


def test_macos_adapter_falls_back_when_speech_framework_missing(mocker):
    """pyobjc-framework-Speech may not be importable even when bundled —
    must degrade to the Google fallback rather than raising."""
    from stt import macos_speech

    mocker.patch.object(macos_speech, "SFSpeechRecognizer", None)
    mocker.patch.object(macos_speech, "_bundle_has_speech_usage_description", return_value=True)

    with patch("speech_recognition.Recognizer") as mock_rec_cls, \
         patch("speech_recognition.AudioFile"):
        mock_rec_cls.return_value.recognize_google.return_value = "음악 틀어줘"
        result = macos_speech.MacOSSpeechAdapter().transcribe(b"fake_audio")

    assert result == "음악 틀어줘"


def test_whisper_api_adapter(mocker):
    from stt.whisper_api import WhisperAPIAdapter
    adapter = WhisperAPIAdapter(api_key="sk-test")
    mock_client = mocker.patch("stt.whisper_api.OpenAI")
    mock_instance = mock_client.return_value
    mock_instance.audio.transcriptions.create.return_value = MagicMock(text="hello world")
    result = adapter.transcribe(b"fake_audio")
    assert result == "hello world"


def test_whisper_local_adapter(mocker):
    from stt.whisper_local import WhisperLocalAdapter
    mock_model = mocker.patch("stt.whisper_local.WhisperModel")
    mock_instance = mock_model.return_value
    mock_instance.transcribe.return_value = (
        [MagicMock(text=" 음악 틀어줘", no_speech_prob=0.05)], MagicMock()
    )
    adapter = WhisperLocalAdapter(model_size="base")
    result = adapter.transcribe(b"fake_audio")
    assert result == "음악 틀어줘"


def test_whisper_local_enables_vad_and_disables_context_carryover(mocker):
    """VAD filtering + no-carryover are what keep silence/noise from
    hallucinating into garbage text — must actually be requested."""
    from stt.whisper_local import WhisperLocalAdapter
    mock_model = mocker.patch("stt.whisper_local.WhisperModel")
    mock_instance = mock_model.return_value
    mock_instance.transcribe.return_value = ([], MagicMock())
    adapter = WhisperLocalAdapter(model_size="base")
    adapter.transcribe(b"fake_audio")
    kwargs = mock_instance.transcribe.call_args.kwargs
    assert kwargs["vad_filter"] is True
    assert kwargs["condition_on_previous_text"] is False


def test_whisper_local_drops_low_confidence_segments(mocker):
    """A segment the model itself flags as probably-not-speech must not leak
    into the transcript even if it produced text."""
    from stt.whisper_local import WhisperLocalAdapter
    mock_model = mocker.patch("stt.whisper_local.WhisperModel")
    mock_instance = mock_model.return_value
    mock_instance.transcribe.return_value = (
        [
            MagicMock(text="??", no_speech_prob=0.92),
            MagicMock(text=" 음악 틀어줘", no_speech_prob=0.05),
        ],
        MagicMock(),
    )
    adapter = WhisperLocalAdapter(model_size="base")
    result = adapter.transcribe(b"fake_audio")
    assert result == "음악 틀어줘"


def test_whisper_local_treats_pure_punctuation_result_as_no_speech(mocker):
    """Regression: 'noise search results in ?? ??' — a transcript with no
    actual letters/digits is a hallucination artifact, not a real command,
    and must come back empty so main.py's empty-command path handles it."""
    from stt.whisper_local import WhisperLocalAdapter
    mock_model = mocker.patch("stt.whisper_local.WhisperModel")
    mock_instance = mock_model.return_value
    mock_instance.transcribe.return_value = (
        [MagicMock(text="?? ??", no_speech_prob=0.3)], MagicMock()
    )
    adapter = WhisperLocalAdapter(model_size="base")
    result = adapter.transcribe(b"fake_audio")
    assert result == ""
