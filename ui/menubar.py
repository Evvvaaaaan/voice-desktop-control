# ui/menubar.py
import rumps


class VoiceDeskMenuBar(rumps.App):
    def __init__(self, agent, hud, settings_window):
        super().__init__("VoiceDesk", icon=None, quit_button="Quit")
        self._agent = agent
        self._hud = hud
        self._settings = settings_window
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
        self.title = "🎤" if self._active else "VoiceDesk"
