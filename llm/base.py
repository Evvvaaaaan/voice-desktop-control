from abc import ABC, abstractmethod


class LLMBase(ABC):
    # Whether this provider can accept image content (screenshots) in messages.
    # Vision-capable adapters override this and build_observation().
    supports_vision: bool = False

    @abstractmethod
    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        """Send messages to LLM, return text response."""
        ...

    def build_observation(self, text: str, screenshot_png: bytes) -> dict:
        """Build a follow-up user message conveying the post-action observation.

        Default (non-vision) providers get a plain text message; the screenshot
        is ignored. Vision-capable adapters override this to attach the image in
        their provider-native format.
        """
        return {"role": "user", "content": text}
