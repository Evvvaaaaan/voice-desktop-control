# ui/menubar.py
import sys
from pathlib import Path

import rumps


def _menubar_icon_path() -> str | None:
    """Locate the menu bar icon in a source checkout or a py2app bundle."""
    here = Path(__file__).resolve().parent
    candidates = [here.parent / "assets" / "menubar-icon.png"]
    executable = getattr(sys, "executable", "")
    if executable:
        exe = Path(executable).resolve()
        # py2app: VoiceDesk.app/Contents/MacOS/VoiceDesk -> Contents/Resources
        candidates.append(exe.parent.parent / "Resources" / "assets" / "menubar-icon.png")
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


class VoiceDeskMenuBar(rumps.App):
    def __init__(self, agent, hud, settings_window, on_activation_callback=None):
        icon = _menubar_icon_path()
        super().__init__(
            "VoiceDesk",
            title=None if icon else "VoiceDesk",
            icon=icon,
            template=True,
            quit_button="Quit",
        )
        self._agent = agent
        self._hud = hud
        self._settings = settings_window
        self._on_activation = on_activation_callback
        self.menu = [
            rumps.MenuItem("Open Settings", callback=self._open_settings),
            rumps.MenuItem("Toggle Listening", callback=self._toggle),
            None,
        ]
        self._active = False

    @rumps.clicked("Open Settings")
    def _open_settings(self, _):
        self._settings.show()

    @rumps.clicked("Toggle Listening")
    def _toggle(self, _):
        self._active = not self._active
        state = "listening" if self._active else "idle"
        self._hud.set_state(state)
        if self._active and self._on_activation:
            self._on_activation()
