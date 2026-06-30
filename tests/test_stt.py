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
    from stt.macos_speech import MacOSSpeechAdapter
    adapter = MacOSSpeechAdapter()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="카카오 열어줘\n", returncode=0)
        result = adapter.transcribe(b"fake_audio")
    assert result == "카카오 열어줘"


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
        [MagicMock(text=" 음악 틀어줘")], MagicMock()
    )
    adapter = WhisperLocalAdapter(model_size="base")
    result = adapter.transcribe(b"fake_audio")
    assert result == "음악 틀어줘"
