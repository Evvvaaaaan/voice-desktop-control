from config.loader import Config
from stt.base import STTBase


def get_stt_adapter(config: Config) -> STTBase:
    provider = config.stt.provider
    if provider == "whisper_api":
        from stt.whisper_api import WhisperAPIAdapter
        return WhisperAPIAdapter(api_key=config.stt.whisper_api_key)
    elif provider == "whisper_local":
        from stt.whisper_local import WhisperLocalAdapter
        return WhisperLocalAdapter(model_size=config.stt.whisper_local_model)
    else:
        from stt.macos_speech import MacOSSpeechAdapter
        return MacOSSpeechAdapter()
