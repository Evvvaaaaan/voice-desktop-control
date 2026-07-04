from pynput import keyboard as kb


class HotkeyListener:
    def __init__(self, binding: str, callback):
        self._binding = binding
        self._callback = callback
        self._listener = None
        self._pressed = set()
        self._fired = False  # edge trigger: one fire per chord press

    def _parse_binding(self) -> set:
        parts = self._binding.lower().split("+")
        key_map = {
            "alt": kb.Key.alt, "space": kb.Key.space,
            "cmd": kb.Key.cmd, "ctrl": kb.Key.ctrl,
        }
        return {key_map.get(p, kb.KeyCode.from_char(p)) for p in parts}

    def _canonical(self, key):
        """Normalize side-specific modifiers (alt_l/alt_r → alt) via pynput."""
        try:
            return self._listener.canonical(key)
        except Exception:
            return key

    def _on_press(self, key):
        self._pressed.add(self._canonical(key))
        if self._keys.issubset(self._pressed):
            # macOS auto-repeat re-delivers on_press while held; fire only on
            # the transition into the full chord.
            if not self._fired:
                self._fired = True
                self._callback()

    def _on_release(self, key):
        self._pressed.discard(self._canonical(key))
        if not self._keys.issubset(self._pressed):
            self._fired = False

    def start(self) -> None:
        self._keys = self._parse_binding()
        self._pressed = set()
        self._fired = False
        self._listener = kb.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
