from abc import ABC, abstractmethod


class LLMBase(ABC):
    @abstractmethod
    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        """Send messages to LLM, return text response."""
        ...
