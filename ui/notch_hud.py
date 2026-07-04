# ui/notch_hud.py
#
# NotchNook-style notch HUD. One shape anchored to the screen's top-center that
# grows downward and widens as it expands (Dynamic-Island metaphor), rendered on
# frosted glass. See docs/superpowers/specs/2026-07-01-notch-hud-redesign-design.md.
#
# The pure helpers at module level (label formatting, mic-bar heights,
# top-center frame math) carry the logic and are unit-tested without AppKit.
import atexit
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from ui.animations import STATE_COLORS, STATE_LABELS

# Per-visual size (width, height) in points. Idle has three sub-visuals; the
# rest map 1:1 to agent states. Sizes mirror NotchNook's proportions scaled to
# VoiceDesk's lighter content (see spec §3).
_SIZES = {
    "idle_collapsed": (190, 10),
    "idle_peek": (380, 42),
    "idle_pinned": (480, 140),
    "listening": (360, 62),
    "processing": (360, 66),
    "executing": (360, 66),
    "success": (360, 66),
    "error": (360, 66),
    "danger_confirm": (460, 100),
    "text_input": (540, 120),
}

# Short, human display labels for each provider id.
_PROVIDER_LABELS = {
    "macos": "로컬",
    "whisper_local": "Whisper",
    "whisper_api": "Whisper API",
    "ollama": "Ollama",
    "claude": "Claude",
    "openai": "GPT",
    "nvidia": "NVIDIA",
}

_HOVER_DWELL_SEC = 0.25  # accidental-trigger guard (spec §2)
_WIDGET_TICK_SEC = 5.0   # pinned-panel refresh cadence (clock, media, routines)


def _label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, (provider or "").title() or "—")


def _short_voice(voice: str) -> str:
    """Compact a voice/model id for the panel (first token, no path)."""
    if not voice:
        return "—"
    return voice.split("/")[-1].split(".")[0].split("-")[0]


def _format_provider_summary(stt, llm, llm_model, tts, tts_voice) -> str:
    """One-line peek text, e.g. 'STT 로컬 · LLM Claude · TTS NVIDIA'."""
    return f"STT {_label(stt)} · LLM {_label(llm)} · TTS {_label(tts)}"


def _format_provider_columns(stt, llm, llm_model, tts, tts_voice) -> list[dict]:
    """Three columns for the pinned panel: title + detail lines per component."""
    return [
        {"title": "STT", "lines": [_label(stt)]},
        {"title": "LLM", "lines": [_label(llm), llm_model or "—"]},
        {"title": "TTS", "lines": [_label(tts), _short_voice(tts_voice)]},
    ]


def _bar_heights(rms: float, num_bars: int = 6) -> list[float]:
    """Map a normalized RMS level (0..1) to per-bar height fractions (0..1).

    A triangular window gives the classic center-tall meter shape; every bar
    scales with the current level, clamped so the meter never fully collapses.
    """
    level = 0.0 if rms < 0 else (1.0 if rms > 1 else float(rms))
    heights = []
    mid = (num_bars - 1) / 2.0 if num_bars > 1 else 0.0
    for i in range(num_bars):
        weight = 1.0 - (abs(i - mid) / (mid + 1)) if mid else 1.0
        h = weight * level
        heights.append(0.08 if h < 0.08 else (1.0 if h > 1.0 else h))
    return heights


def _frame_for(size, screen_w, screen_h):
    """Window frame (x, y, w, h) pinned to the screen's top-center.

    x centers the panel; y places its top edge at the screen top so every
    resize appears to grow out of / retract into the notch.
    """
    w, h = size
    x = (screen_w - w) / 2.0
    y = screen_h - h
    return (x, y, w, h)


# Collapsed pill vs the physical notch (NotchNook look, verified against the
# user's reference recording): a bit wider than the notch and hanging a small
# black lip below the menu bar, so the shape reads as a grown notch.
_COLLAPSED_EXTRA_W = 24
_COLLAPSED_LIP = 8


def _visual_size(visual, top_inset=0.0, notch_size=None, sizes=_SIZES):
    """(width, total_height, content_height) for a visual on this screen.

    On a screen with a physical notch (`top_inset` > 0) the window's top
    `top_inset` points sit behind the notch/menu-bar row, so every expanded
    visual grows taller by that amount while its content keeps the spec'd
    height, laid out in the visible bottom region. The collapsed idle pill
    wraps the notch itself plus a small visible lip below the menu bar.
    """
    w, h = sizes.get(visual, sizes["processing"])
    if visual == "idle_collapsed":
        if notch_size:
            ch = notch_size[1] + _COLLAPSED_LIP
            return (notch_size[0] + _COLLAPSED_EXTRA_W, ch, ch)
        return (w, h, h)
    return (w, h + top_inset, h)


def _truncate(s: str, n: int = 44) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# Pinned-panel size grows when the NotchNook-style widgets (clock / now
# playing) are enabled; without them it keeps the original compact layout.
# Widened further (was 640) for the album-art thumbnail + prev/play/next
# transport controls in the media card, and taller (was 210) for the
# saved-routines row underneath the provider columns.
_PINNED_WITH_WIDGETS = (760, 250)

_WEEKDAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _pinned_size(show_clock: bool, show_media: bool):
    if show_clock or show_media:
        return _PINNED_WITH_WIDGETS
    return _SIZES["idle_pinned"]


def _format_clock(now) -> tuple[str, str]:
    """(time, date) strings for the clock widget, e.g. ('16:52', '7월 2일 수요일')."""
    return (
        f"{now.hour:02d}:{now.minute:02d}",
        f"{now.month}월 {now.day}일 {_WEEKDAYS_KO[now.weekday()]}요일",
    )


def _media_line(media) -> tuple[str, str]:
    """(title, artist) display lines for the now-playing widget."""
    if not media:
        return ("재생 중인 음악 없음", "")
    title, artist = media[0], media[1]
    return (_truncate(title, 24), _truncate(artist or "", 24))


# Apps queried for now-playing info / media control, in lookup order.
_MEDIA_PLAYERS = (
    ("com.apple.Music", "Music"),
    ("com.spotify.client", "Spotify"),
)


def _now_playing():
    """(title, artist, app_name, is_playing) from Music or Spotify, or None
    if neither app has a loaded track.

    Includes PAUSED tracks, not just playing ones — otherwise pausing music
    would make the whole media card (and its resume/next/prev buttons)
    disappear, with no way to get back to it short of starting a new track
    from inside the player itself.

    Only queries players that are ALREADY RUNNING — `tell application` would
    otherwise launch them. Runs osascript, so first use triggers a one-time
    Automation permission prompt for that player. `app_name` is returned so
    callers (artwork fetch, prev/next control) know which app to address
    without re-detecting it.
    """
    import subprocess
    try:
        import AppKit
    except ImportError:
        return None
    for bundle_id, app_name in _MEDIA_PLAYERS:
        try:
            running = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
            if not running:
                continue
            script = (
                f'tell application "{app_name}" to if player state is not stopped then '
                'return (name of current track) & "|||" & (artist of current track)'
                ' & "|||" & (player state as string)'
            )
            res = subprocess.run(["osascript", "-e", script],
                                 capture_output=True, text=True, timeout=3)
            out = (res.stdout or "").strip()
            if res.returncode == 0 and out.count("|||") == 2:
                title, artist, state = out.split("|||", 2)
                return (title.strip(), artist.strip(), app_name, state.strip() == "playing")
        except Exception:
            continue
    return None


def _fetch_artwork(app_name: str) -> str | None:
    """Small base64-PNG thumbnail of the current track's artwork, or None.

    Music.app exposes raw artwork bytes directly; Spotify only exposes an
    artwork URL that has to be downloaded. Either way the source image can be
    several hundred KB at full resolution, so it's downsized before being
    embedded in the JSON payload sent to the Swift renderer.
    """
    import subprocess
    import tempfile
    import os
    import base64
    import io

    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as f:
        tmp_path = f.name
    try:
        if app_name == "Spotify":
            url = subprocess.run(
                ["osascript", "-e", 'tell application "Spotify" to artwork url of current track'],
                capture_output=True, text=True, timeout=3,
            ).stdout.strip()
            if not url:
                return None
            import urllib.request
            with urllib.request.urlopen(url, timeout=4) as resp:
                data = resp.read()
            with open(tmp_path, "wb") as f:
                f.write(data)
        else:
            script = (
                f'tell application "{app_name}"\n'
                '  set artData to data of artwork 1 of current track\n'
                f'  set fileRef to open for access POSIX file "{tmp_path}" with write permission\n'
                '  set eof fileRef to 0\n'
                '  write artData to fileRef\n'
                '  close access fileRef\n'
                'end tell'
            )
            res = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=4)
            if res.returncode != 0 or os.path.getsize(tmp_path) == 0:
                return None

        from PIL import Image
        img = Image.open(tmp_path).convert("RGB")
        img.thumbnail((160, 160))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _load_routine_names() -> list[str]:
    """Saved routine names for the pinned panel's one-click launch list.

    Uses the same VOICEDESK_ROUTINES path main.py syncs into the environment
    for agent/tools.py's run_routine action, so the panel always lists
    exactly what a voice "~루틴 실행해줘" command could run.
    """
    try:
        from routines.manager import RoutineManager
        mgr = RoutineManager(os.environ.get("VOICEDESK_ROUTINES", "data/routines.json"))
        return [r["name"] for r in mgr.load_all()]
    except Exception:
        return []


def _battery_status():
    """(percent, charging) read from `pmset -g batt`, or (None, False) if
    unavailable (desktop Mac, parse failure, etc.)."""
    import re
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                             text=True, timeout=2).stdout
        m = re.search(r"(\d+)%", out)
        if not m:
            return (None, False)
        charging = "AC Power" in out or "charging" in out
        return (int(m.group(1)), charging)
    except Exception:
        return (None, False)


def _battery_info() -> str:
    """Short battery line for the pinned panel, e.g. '⚡ 78%' ('' if unknown)."""
    percent, charging = _battery_status()
    if percent is None:
        return ""
    return f"{'⚡' if charging else '🔋'} {percent}%"


class TextInputRequest:
    """One-shot text answer from the notch input field.

    resolve(text) with the confirmed string, or resolve(None) on cancel;
    wait() returns the value, or None on cancel/timeout."""

    def __init__(self):
        self._event = threading.Event()
        self._value = None

    def resolve(self, text) -> None:
        if not self._event.is_set():
            self._value = text
            self._event.set()

    def wait(self, timeout: float):
        self._event.wait(timeout)
        return self._value


def _resource_candidates(name: str) -> list[Path]:
    """Likely source/binary locations in source checkout and py2app bundles."""
    here = Path(__file__).resolve().parent
    candidates = [
        here / "swift_hud" / name,
    ]
    executable = getattr(sys, "executable", "")
    if executable:
        exe = Path(executable).resolve()
        # py2app: VoiceDesk.app/Contents/MacOS/VoiceDesk -> Contents/Resources
        candidates.append(exe.parent.parent / "Resources" / "swift_hud" / name)
        candidates.append(exe.parent.parent / "Resources" / name)
    return candidates


def _find_existing_resource(name: str) -> Path | None:
    for candidate in _resource_candidates(name):
        if candidate.exists():
            return candidate
    return None


def _swift_hud_build_path(source: Path) -> Path:
    stamp = f"{source.stat().st_mtime_ns:x}"
    root = Path(tempfile.gettempdir()) / "voicedesk-swift-hud"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"VoiceDeskHUD-{stamp}"


def _swift_hud_executable() -> Path | None:
    """Return a Swift HUD executable, compiling from source when necessary."""
    override = os.environ.get("VOICEDESK_SWIFT_HUD_BIN")
    if override:
        candidate = Path(override).expanduser()
        if candidate.exists():
            return candidate

    bundled = _find_existing_resource("VoiceDeskHUD")
    if bundled is not None and os.access(bundled, os.X_OK):
        return bundled

    source = _find_existing_resource("VoiceDeskHUD.swift")
    if source is None:
        return None

    target = _swift_hud_build_path(source)
    if target.exists() and target.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return target

    swiftc = os.environ.get("SWIFTC", "swiftc")
    try:
        res = subprocess.run(
            [swiftc, str(source), "-o", str(target)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        print(f"[HUD] Swift HUD compile failed: {exc}", file=sys.stderr)
        return None
    if res.returncode != 0:
        stderr = (res.stderr or res.stdout or "").strip()
        print(f"[HUD] Swift HUD compile failed: {stderr}", file=sys.stderr)
        return None
    try:
        target.chmod(0o755)
    except Exception:
        pass
    return target


class _SwiftHUDBridge:
    """Small JSON-line bridge to the native Swift HUD helper."""

    def __init__(self, on_event):
        self._on_event = on_event
        self._process = None
        self._lock = threading.Lock()
        self._stderr_tail: list[str] = []

    def start(self) -> bool:
        if platform.system() != "Darwin":
            return False
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return True
            exe = _swift_hud_executable()
            if exe is None:
                return False
            try:
                self._process = subprocess.Popen(
                    [str(exe)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
            except Exception as exc:
                print(f"[HUD] Swift HUD launch failed: {exc}", file=sys.stderr)
                self._process = None
                return False
            threading.Thread(target=self._read_stdout, daemon=True).start()
            threading.Thread(target=self._read_stderr, daemon=True).start()
            atexit.register(self.stop)
            return True

    def send(self, payload: dict) -> bool:
        if not self.start():
            return False
        with self._lock:
            proc = self._process
            if proc is None or proc.poll() is not None or proc.stdin is None:
                return False
            try:
                proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                proc.stdin.flush()
                return True
            except Exception:
                return False

    def stop(self) -> None:
        with self._lock:
            proc, self._process = self._process, None
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin is not None:
                proc.stdin.write(json.dumps({"type": "quit"}) + "\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass

    def _read_stdout(self) -> None:
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except Exception:
                continue
            try:
                self._on_event(event)
            except Exception:
                pass

    def _read_stderr(self) -> None:
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            line = line.rstrip()
            if not line:
                continue
            self._stderr_tail.append(line)
            self._stderr_tail = self._stderr_tail[-8:]
            print(f"[HUD] {line}", file=sys.stderr)


class NotchHUD:
    def __init__(self):
        self._state = "idle"
        self._metrics: dict = {}
        # idle sub-state drivers (only meaningful while state == "idle")
        self._hover_inside = False   # raw pointer presence
        self._hovering = False       # hover-expanded (post-dwell)
        self._pinned = False         # click-toggled
        # provider info + mic level + last transcribed command
        self._provider = None        # tuple(stt, llm, llm_model, tts, tts_voice)
        self._mic_level = 0.0
        self._transcript = ""
        # pending danger confirmation (safety.guard.ConfirmDecision)
        self._danger_decision = None
        self._danger_hit_zones = []   # [((x, y, w, h), allow)] in body coords
        # NotchNook-style widgets (pinned panel)
        self._show_clock = True
        self._show_media = True
        self._show_battery = True
        self._hover_to_expand = True
        self._interaction_sounds = True
        self._media = None            # (title, artist, app_name) or None
        self._media_artwork = None    # base64 PNG thumbnail for the current track
        self._battery = ""
        self._tick_armed = False
        # pending long-text input (TextInputRequest)
        self._text_request = None
        self._text_prompt = ""
        self._text_prefill = ""
        # gear icon in the pinned panel opens Settings, wired by main()
        self._on_open_settings = None
        # Native Swift renderer
        self._bridge = None
        self._visible = False
        self._hover_timer = None
        self._tick_timer = None
        self._initialized = False

    # ---- derived visual -------------------------------------------------
    def _visual(self) -> str:
        if self._state == "idle":
            if self._pinned:
                return "idle_pinned"
            if self._hovering:
                return "idle_peek"
            return "idle_collapsed"
        return self._state if self._state in _SIZES else "processing"

    # ---- interaction logic (pure; ObjC handlers delegate here) ----------
    def _hover_enter(self):
        self._hover_inside = True
        self._schedule_hover_expand()

    def _hover_expand_fire(self):
        if self._hover_inside and self._state == "idle":
            self._hovering = True
            self._render()

    def _hover_exit(self):
        self._hover_inside = False
        self._hovering = False
        self._render()

    def _toggle_pin(self):
        if self._state == "idle":
            self._pinned = not self._pinned
            if self._pinned:
                self._fetch_media_async()
            self._render()

    def _schedule_hover_expand(self):
        """Arm the dwell timer. Isolated so tests can drive it synchronously."""
        if not self._hover_to_expand:
            return
        try:
            if self._hover_timer is not None:
                self._hover_timer.cancel()
            self._hover_timer = threading.Timer(_HOVER_DWELL_SEC, self._hover_expand_fire)
            self._hover_timer.daemon = True
            self._hover_timer.start()
        except Exception:
            pass

    # ---- Swift renderer dispatch -----------------------------------------
    def _dispatch_render(self) -> None:
        self._render()

    def _dispatch_bars(self) -> None:
        self._render_bars()

    # ---- public API -----------------------------------------------------
    def set_state(self, state: str) -> None:
        self._state = state
        if state != "idle":
            # Active-state UI always wins; drop any idle expansion.
            self._pinned = False
            self._hovering = False
            self._hover_inside = False
        self._ensure_init()
        if not self._initialized:
            return
        self._dispatch_render()

    def set_provider_info(self, stt, llm, llm_model, tts, tts_voice) -> None:
        self._provider = (stt, llm, llm_model, tts, tts_voice)
        if self._initialized and self._state == "idle" and (self._pinned or self._hovering):
            self._dispatch_render()

    def set_transcript(self, text: str) -> None:
        """Show the recognized command under the state label while active."""
        self._transcript = (text or "").strip()
        if self._initialized and self._state in ("processing", "executing", "success", "error"):
            self._dispatch_render()

    def update_mic_level(self, rms: float) -> None:
        self._mic_level = rms
        if self._initialized and self._state == "listening":
            self._dispatch_bars()

    def set_widgets(self, show_clock: bool, show_media: bool, show_battery: bool = True,
                    hover_to_expand: bool = True, interaction_sounds: bool = True) -> None:
        """Configure the pinned-panel widgets and interaction behavior."""
        self._show_clock = bool(show_clock)
        self._show_media = bool(show_media)
        self._show_battery = bool(show_battery)
        self._hover_to_expand = bool(hover_to_expand)
        self._interaction_sounds = bool(interaction_sounds)
        if self._initialized and self._state == "idle" and self._pinned:
            self._dispatch_render()

    def _run_routine_async(self, name: str) -> None:
        """Execute a saved routine (from a pinned-panel click) off the main
        thread — a routine can chain several AppleScript/UI actions and must
        not block rendering. Speaks a short confirmation since a silent
        background click otherwise gives the user no feedback at all.
        """
        import threading

        def _work():
            from agent import tools
            try:
                result = tools.dispatch("run_routine", {"name": name})
            except Exception as e:
                result = f"error: {e}"
            try:
                from actions.tts import speak
                if result == "routine_done":
                    speak(f"{name} 루틴을 실행했어요.")
                else:
                    speak(f"{name} 루틴 실행에 실패했어요.")
            except Exception:
                pass

        threading.Thread(target=_work, daemon=True).start()

    def _control_media_async(self, applescript_command: str) -> None:
        """Send a transport command (previous track / next track / playpause)
        to whichever app is currently playing, then refresh the widget so the
        panel reflects the new track/play-state without waiting for the next
        5s tick."""
        app_name = self._media[2] if self._media else None
        if not app_name:
            return
        import threading

        def _work():
            try:
                from actions.applescript import run_applescript
                run_applescript(f'tell application "{app_name}" to {applescript_command}')
            except Exception:
                pass
            import time
            time.sleep(0.3)   # let the player's track/state settle first
            self._fetch_media_async()

        threading.Thread(target=_work, daemon=True).start()

    def _fetch_media_async(self) -> None:
        """Refresh now-playing info (and artwork, on track change) off the
        main thread, then re-render."""
        if not self._show_media:
            return
        import threading

        def _work():
            prev = self._media
            media = _now_playing()
            self._media = media
            # Artwork extraction (osascript round-trip + image decode) is the
            # expensive part of this refresh — only redo it when the track
            # actually changed, not on every 5s tick.
            prev_key = (prev[0], prev[1]) if prev else None
            new_key = (media[0], media[1]) if media else None
            if new_key != prev_key:
                self._media_artwork = _fetch_artwork(media[2]) if media else None
            if self._state == "idle" and self._pinned:
                self._dispatch_render()

        threading.Thread(target=_work, daemon=True).start()

    def _arm_widget_tick(self) -> None:
        """Periodic pinned-panel refresh (clock, track changes) while pinned.

        Called from _render_payload() every time the pinned panel is drawn,
        and re-armed at the end of _widget_tick() itself — together these
        keep a refresh chain alive for as long as the panel stays open, and
        let it die naturally once the panel closes (neither call site fires
        again, so nothing re-arms the timer).
        """
        if self._tick_armed:
            return
        try:
            self._tick_armed = True
            self._tick_timer = threading.Timer(_WIDGET_TICK_SEC, self._widget_tick)
            self._tick_timer.daemon = True
            self._tick_timer.start()
        except Exception:
            self._tick_armed = False

    def _widget_tick(self) -> None:
        self._tick_armed = False
        if self._state == "idle" and self._pinned:
            self._fetch_media_async()
            self._render()   # re-renders the payload, which re-arms the next tick

    def request_text_input(self, prompt: str, prefill: str = "",
                           timeout: float = 180.0):
        """Show the notch text field and block until the user confirms/cancels.

        Returns the confirmed text, or None on cancel/timeout. Long text is
        far more reliable typed than dictated — the LLM's draft is prefilled
        so the user only has to review or fix it. Restores focus to the app
        that was frontmost so the confirmed text lands where it should."""
        front = None
        try:
            import AppKit
            front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        except Exception:
            pass

        req = TextInputRequest()
        self._text_prompt = prompt
        self._text_prefill = prefill
        self._text_request = req
        prev_state = self._state
        self.set_state("text_input")
        value = req.wait(timeout)
        self._text_request = None
        self.set_state(prev_state if prev_state != "text_input" else "executing")

        if front is not None:
            try:
                import AppKit
                import time
                front.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
                time.sleep(0.4)   # let focus settle before typing begins
            except Exception:
                pass
        return value

    def _resolve_text(self, value) -> None:
        req, self._text_request = self._text_request, None
        if req is not None:
            try:
                req.resolve(value)
            except Exception:
                pass

    def set_open_settings_callback(self, callback) -> None:
        """Called when the pinned panel's gear icon is clicked."""
        self._on_open_settings = callback

    def arm_danger_prompt(self, decision) -> None:
        """Route the danger_confirm buttons to `decision` (guard's waiter)."""
        self._danger_decision = decision
        if self._initialized and self._state == "danger_confirm":
            self._dispatch_render()

    def _danger_resolve(self, allow: bool) -> None:
        decision, self._danger_decision = self._danger_decision, None
        if decision is not None:
            try:
                decision.resolve(allow)
            except Exception:
                pass

    def _click_at(self, x: float, y: float) -> None:
        """Route a click (body coordinates): danger buttons first, else pin.

        Unit tests drive this pure helper directly. The Swift renderer sends
        dedicated dangerAllow/dangerDeny events for real button clicks.
        """
        for (fx, fy, fw, fh), allow in self._danger_hit_zones:
            if fx <= x <= fx + fw and fy <= y <= fy + fh:
                self._danger_resolve(allow)
                return
        self._toggle_pin()

    def update_metrics(self, metrics: dict) -> None:
        self._metrics = metrics

    def show(self) -> None:
        self._ensure_init()
        if not self._initialized:
            return
        self._visible = True
        self._render()

    def hide(self) -> None:
        self._visible = False
        if not self._initialized:
            return
        try:
            self._bridge.send({"type": "hide"})
        except Exception:
            pass

    # ---- Swift construction / rendering ----------------------------------
    def _ensure_init(self):
        if self._initialized:
            return
        self._bridge = _SwiftHUDBridge(self._on_swift_event)
        self._initialized = self._bridge.start()

    def _on_swift_event(self, event: dict) -> None:
        name = event.get("event")
        if name == "hoverEnter":
            self._hover_enter()
        elif name == "hoverExit":
            self._hover_exit()
        elif name == "click":
            self._toggle_pin()
        elif name == "dangerAllow":
            self._danger_resolve(True)
        elif name == "dangerDeny":
            self._danger_resolve(False)
        elif name == "openSettings":
            if self._on_open_settings:
                try:
                    self._on_open_settings()
                except Exception:
                    pass
        elif name == "textSubmit":
            self._resolve_text(str(event.get("text", "")))
        elif name == "textCancel":
            self._resolve_text(None)
        elif name == "runRoutine":
            routine_name = str(event.get("name", "")).strip()
            if routine_name:
                self._run_routine_async(routine_name)
        elif name == "mediaPrev":
            self._control_media_async("previous track")
        elif name == "mediaNext":
            self._control_media_async("next track")
        elif name == "mediaPlayPause":
            self._control_media_async("playpause")

    def _render_payload(self) -> dict:
        visual = self._visual()
        sizes = _SIZES
        routine_names = []
        if visual == "idle_pinned":
            self._arm_widget_tick()
            sizes = dict(_SIZES)
            sizes["idle_pinned"] = _pinned_size(self._show_clock, self._show_media)
            routine_names = _load_routine_names()
        base_w, base_h = sizes.get(visual, sizes["processing"])
        stt, llm, lm, tts, tv = self._provider or ("", "", "", "", "")
        media_title, media_artist = _media_line(self._media)
        clock_time, clock_date = _format_clock(datetime.now())
        color = STATE_COLORS.get(self._state, (1.0, 1.0, 1.0, 1.0))
        battery_percent, battery_charging = (None, False)
        if visual == "idle_pinned" and self._show_battery:
            battery_percent, battery_charging = _battery_status()
            self._battery = "" if battery_percent is None else \
                f"{'⚡' if battery_charging else '🔋'} {battery_percent}%"
        elif not self._show_battery:
            self._battery = ""
        return {
            "type": "render",
            "visible": self._visible,
            "visual": visual,
            "state": self._state,
            "stateLabel": STATE_LABELS.get(self._state, ""),
            "stateColor": list(color),
            "baseWidth": base_w,
            "baseHeight": base_h,
            "providerSummary": _format_provider_summary(stt, llm, lm, tts, tv),
            "providerColumns": _format_provider_columns(stt, llm, lm, tts, tv),
            "transcript": _truncate(self._transcript),
            "micBars": _bar_heights(self._mic_level),
            "showClock": self._show_clock,
            "showMedia": self._show_media,
            "clockTime": clock_time,
            "clockDate": clock_date,
            "mediaTitle": media_title,
            "mediaArtist": media_artist,
            "mediaPlaying": bool(self._media[3]) if self._media else False,
            "mediaArtwork": self._media_artwork or "",
            "mediaPlayerApp": self._media[2] if self._media else "",
            "routines": routine_names,
            "battery": self._battery,
            "batteryPercent": battery_percent,
            "batteryCharging": battery_charging,
            "interactionSounds": self._interaction_sounds,
            "inputPrompt": self._text_prompt,
            "inputPrefill": self._text_prefill,
        }

    def _render(self):
        if not self._initialized:
            return
        try:
            self._bridge.send(self._render_payload())
        except Exception:
            pass

    def _render_bars(self):
        """Refresh the Swift bar view with the current mic level."""
        self._render()
