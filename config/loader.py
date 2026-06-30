from dataclasses import dataclass, field, asdict
from typing import Any
import yaml


@dataclass
class STTConfig:
    provider: str = "macos"
    whisper_api_key: str = ""
    whisper_local_model: str = "base"


@dataclass
class LLMConfig:
    provider: str = "ollama"
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"


@dataclass
class ActivationConfig:
    wake_word: bool = True
    wake_phrase: str = "hey desk"
    hotkey: bool = True
    hotkey_binding: str = "alt+space"


@dataclass
class TTSConfig:
    voice: str = "Yuna"
    rate: int = 200


@dataclass
class SafetyConfig:
    require_confirmation: bool = True


@dataclass
class Config:
    stt: STTConfig = field(default_factory=STTConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    activation: ActivationConfig = field(default_factory=ActivationConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)


def _from_dict(cls, data: dict) -> Any:
    fields = {f.name for f in cls.__dataclass_fields__.values()}
    return cls(**{k: v for k, v in data.items() if k in fields})


def load_config(path: str = "config.yaml") -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return Config(
        stt=_from_dict(STTConfig, raw.get("stt", {})),
        llm=_from_dict(LLMConfig, raw.get("llm", {})),
        activation=_from_dict(ActivationConfig, raw.get("activation", {})),
        tts=_from_dict(TTSConfig, raw.get("tts", {})),
        safety=_from_dict(SafetyConfig, raw.get("safety", {})),
    )


def save_config(config: Config, path: str = "config.yaml") -> None:
    with open(path, "w") as f:
        yaml.dump(asdict(config), f, default_flow_style=False, allow_unicode=True)
