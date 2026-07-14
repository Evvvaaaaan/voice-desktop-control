from dataclasses import dataclass, field, asdict
from typing import Any
import os
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
    nvidia_api_key: str = ""
    nvidia_model: str = "meta/llama-4-maverick-17b-128e-instruct"


@dataclass
class ActivationConfig:
    wake_word: bool = True
    wake_phrase: str = "hey desk"
    hotkey: bool = True
    hotkey_binding: str = "alt+space"
    continuous: bool = True   # auto re-listen after a successful command
    wake_vad_speech_amp: int = 500     # int16 mic amplitude that counts as speech
    wake_vad_silence_frames: int = 5   # consecutive silent frames (~80ms each) that end an utterance


@dataclass
class TTSConfig:
    provider: str = "macos"          # macos | nvidia
    voice: str = "Yuna"
    rate: int = 200
    nvidia_api_key: str = ""
    nvidia_function_id: str = ""
    nvidia_voice: str = "Chatterbox-Multilingual.ko-KR.Male"
    nvidia_language_code: str = "ko-KR"


@dataclass
class SafetyConfig:
    require_confirmation: bool = True


@dataclass
class HUDConfig:
    show_clock: bool = True    # clock widget in the pinned notch panel
    show_media: bool = True    # now-playing widget in the pinned notch panel
    show_battery: bool = True  # battery level in the pinned notch panel
    hover_to_expand: bool = True   # auto-expand on hover vs. click-only
    interaction_sounds: bool = True  # short sound on pin/success/error/listening


@dataclass
class MemoryConfig:
    enabled: bool = True
    embedding_provider: str = "auto"     # auto | openai | nvidia | ollama | off
    openai_embedding_model: str = "text-embedding-3-small"
    nvidia_embedding_model: str = "nvidia/nv-embedqa-e5-v5"
    ollama_embedding_model: str = "nomic-embed-text"
    retrieval_top_k: int = 3


@dataclass
class SuggestionConfig:
    enabled: bool = True
    check_interval_sec: int = 300
    startup_grace_sec: int = 300       # skip first minutes after launch
    min_pattern_days: int = 3          # distinct days in an hour to qualify
    cooldown_min: int = 60             # global: at most 1 suggestion per hour
    recent_run_suppress_min: int = 60  # don't suggest a just-run command


@dataclass
class Config:
    stt: STTConfig = field(default_factory=STTConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    activation: ActivationConfig = field(default_factory=ActivationConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    hud: HUDConfig = field(default_factory=HUDConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    suggestion: SuggestionConfig = field(default_factory=SuggestionConfig)


def _from_dict(cls, data: dict) -> Any:
    fields = {f.name for f in cls.__dataclass_fields__.values()}
    return cls(**{k: v for k, v in data.items() if k in fields})


def load_config(path: str = "config.yaml") -> Config:
    if not os.path.exists(path):
        return Config()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return Config(
        stt=_from_dict(STTConfig, raw.get("stt", {})),
        llm=_from_dict(LLMConfig, raw.get("llm", {})),
        activation=_from_dict(ActivationConfig, raw.get("activation", {})),
        tts=_from_dict(TTSConfig, raw.get("tts", {})),
        safety=_from_dict(SafetyConfig, raw.get("safety", {})),
        hud=_from_dict(HUDConfig, raw.get("hud", {})),
        memory=_from_dict(MemoryConfig, raw.get("memory", {})),
        suggestion=_from_dict(SuggestionConfig, raw.get("suggestion", {})),
    )


def save_config(config: Config, path: str = "config.yaml") -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(asdict(config), f, default_flow_style=False, allow_unicode=True)
