from pynput import keyboard as kb


class HotkeyListener:
    def __init__(self, binding: str, callback):
        self._binding = binding
        self._callback = callback
        self._listener = None

    def _parse_binding(self) -> set:
        parts = self._binding.lower().split("+")
        key_map = {
            "alt": kb.Key.alt, "space": kb.Key.space,
            "cmd": kb.Key.cmd, "ctrl": kb.Key.ctrl,
        }
        return {key_map.get(p, kb.KeyCode.from_char(p)) for p in parts}

    def start(self) -> None:
        keys = self._parse_binding()
        pressed = set()

        def on_press(key):
            pressed.add(key)
            if keys.issubset(pressed):
                self._callback()

        def on_release(key):
            pressed.discard(key)

        self._listener = kb.Listener(on_press=on_press, on_release=on_release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
