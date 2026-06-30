from collections import deque


SYSTEM_PROMPT = """You are VoiceDesk, a macOS desktop assistant controlled by voice.
Respond ONLY with JSON: {"action": "<tool>", "params": {...}, "done": true/false, "response": "<text>"}
Available actions: launch_app, click, type_text, press_key, scroll, run_applescript, screenshot, run_routine, speak_only.
For speak_only, just set response text and done=true with no other action.
Always verify success. Max 5 iterations."""


class ConversationContext:
    def __init__(self, max_turns: int = 5):
        self._turns: deque[tuple[str, str]] = deque(maxlen=max_turns)

    def add_turn(self, user: str, assistant: str) -> None:
        self._turns.append((user, assistant))

    def to_messages(self, current_user: str | None = None) -> list[dict]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for user_msg, asst_msg in self._turns:
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": asst_msg})
        if current_user:
            messages.append({"role": "user", "content": current_user})
        return messages
