import pytest
import yaml
from config.loader import load_config, save_config

def test_load_defaults(default_config_dict, tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(default_config_dict))
    config = load_config(str(cfg_file))
    assert config.stt.provider == default_config_dict["stt"]["provider"]
    assert config.llm.provider == default_config_dict["llm"]["provider"]
    assert config.activation.hotkey is default_config_dict["activation"]["hotkey"]

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
    assert config.llm.nvidia_model == "meta/llama-4-maverick-17b-128e-instruct"
    assert config.llm.nvidia_api_key == ""
    assert config.tts.provider == "macos"
    assert config.tts.nvidia_voice == "Chatterbox-Multilingual.ko-KR.Male"
    assert config.tts.nvidia_language_code == "ko-KR"


def test_nvidia_provider_roundtrip(default_config_dict, tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(default_config_dict))
    config = load_config(str(cfg_file))
    config.llm.provider = "nvidia"
    config.llm.nvidia_api_key = "nvapi-test"
    save_config(config, str(cfg_file))
    reloaded = load_config(str(cfg_file))
    assert reloaded.llm.provider == "nvidia"
    assert reloaded.llm.nvidia_api_key == "nvapi-test"


def test_nvidia_tts_provider_roundtrip(default_config_dict, tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(default_config_dict))
    config = load_config(str(cfg_file))
    config.tts.provider = "nvidia"
    config.tts.nvidia_api_key = "nvapi-tts-test"
    config.tts.nvidia_function_id = "func-id-123"
    save_config(config, str(cfg_file))
    reloaded = load_config(str(cfg_file))
    assert reloaded.tts.provider == "nvidia"
    assert reloaded.tts.nvidia_api_key == "nvapi-tts-test"
    assert reloaded.tts.nvidia_function_id == "func-id-123"


def test_hud_config_defaults_and_roundtrip(tmp_path):
    from config.loader import Config, load_config, save_config
    cfg = Config()
    assert cfg.hud.show_clock is True
    assert cfg.hud.show_media is True
    assert cfg.hud.show_battery is True
    assert cfg.hud.hover_to_expand is True
    assert cfg.hud.interaction_sounds is True
    cfg.hud.show_clock = False
    cfg.hud.show_battery = False
    cfg.hud.hover_to_expand = False
    cfg.hud.interaction_sounds = False
    p = str(tmp_path / "c.yaml")
    save_config(cfg, p)
    loaded = load_config(p)
    assert loaded.hud.show_clock is False
    assert loaded.hud.show_media is True
    assert loaded.hud.show_battery is False
    assert loaded.hud.hover_to_expand is False
    assert loaded.hud.interaction_sounds is False


def test_hud_config_missing_section_uses_defaults(tmp_path):
    from config.loader import load_config
    p = str(tmp_path / "c.yaml")
    with open(p, "w") as f:
        f.write("stt:\n  provider: macos\n")   # old config without hud section
    assert load_config(p).hud.show_clock is True
