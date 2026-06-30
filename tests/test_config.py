import pytest
import yaml
import tempfile
import os
from config.loader import load_config, save_config, Config, STTConfig, LLMConfig

def test_load_defaults(default_config_dict, tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(default_config_dict))
    config = load_config(str(cfg_file))
    assert config.stt.provider == "macos"
    assert config.llm.provider == "ollama"
    assert config.activation.hotkey is True

def test_roundtrip(default_config_dict, tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(default_config_dict))
    config = load_config(str(cfg_file))
    config.stt.provider = "whisper_api"
    save_config(config, str(cfg_file))
    reloaded = load_config(str(cfg_file))
    assert reloaded.stt.provider == "whisper_api"

def test_missing_optional_keys(tmp_path):
    minimal = {"stt": {"provider": "macos"}, "llm": {"provider": "ollama"},
               "activation": {}, "tts": {}, "safety": {}}
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(minimal))
    config = load_config(str(cfg_file))
    assert config.stt.whisper_api_key == ""
    assert config.llm.claude_model == "claude-sonnet-4-6"
