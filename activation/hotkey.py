import keyboard


class HotkeyListener:
    """Listens for global hotkey triggers and invokes a callback."""

    def __init__(self, binding: str, callback):
        """
        Initialize hotkey listener.

        Args:
            binding: Hotkey binding string (e.g. "alt+space", "cmd+space")
            callback: Callable to invoke when hotkey is pressed
        """
        self._binding = binding
        self._callback = callback
        self._hotkey_id = None

    def start(self) -> None:
        """Start listening for the hotkey."""
        self._hotkey_id = keyboard.add_hotkey(self._binding, self._callback)

    def stop(self) -> None:
        """Stop listening for the hotkey."""
        if self._hotkey_id is not None:
            keyboard.remove_hotkey(self._hotkey_id)
            self._hotkey_id = None
