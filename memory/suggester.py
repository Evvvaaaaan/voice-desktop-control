import sys
import threading
from datetime import datetime, timedelta, timezone

from memory.store import MemoryStore

# Decline is checked FIRST: "아니요, 됐네요" contains "네".
_DECLINE_WORDS = ("아니", "안 해", "안해", "싫어", "하지 마", "하지마",
                  "나중에", "됐어", "no")
_ACCEPT_WORDS = ("네", "예", "그래", "좋아", "해줘", "해 줘", "오케이",
                 "yes", "ok")
# Single syllables false-positive as substrings of almost anything — they
# only count as an exact (stripped) answer.
_ACCEPT_EXACT = ("어", "응", "예")


def _parse_answer(text: str) -> bool | None:
    """True = accept, False = decline, None = silence/unclear."""
    cleaned = text.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if any(w in lowered for w in _DECLINE_WORDS):
        return False
    if cleaned in _ACCEPT_EXACT or any(w in lowered for w in _ACCEPT_WORDS):
        return True
    return None


class SuggestionEngine:
    """Proactively offers a time-of-day-recurring command via TTS + voice
    yes/no, based on the tier-5 hourly_commands pattern."""

    def __init__(self, store: MemoryStore, config, speak_fn, run_command_fn,
                 begin_session, end_session, listen_fn=None, hud=None):
        self._store = store
        self._config = config
        self._speak = speak_fn
        self._run_command = run_command_fn
        self._begin_session = begin_session
        self._end_session = end_session
        if listen_fn is None:
            from stt.confirm import listen_for_confirmation
            listen_fn = listen_for_confirmation
        self._listen = listen_fn
        self._hud = hud
        self._stop = threading.Event()

    # ----- lifecycle -----

    def start_background(self) -> threading.Thread:
        thread = threading.Thread(target=self._loop, daemon=True,
                                  name="voicedesk-suggester")
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # Startup grace: let wake-word init and the summarizer settle first.
        if self._stop.wait(self._config.startup_grace_sec):
            return
        while not self._stop.wait(self._config.check_interval_sec):
            try:
                self.tick(datetime.now().astimezone())
            except Exception as e:
                print(f"[Suggest] tick failed: {e}", file=sys.stderr)

    # ----- core -----

    def tick(self, now: datetime) -> bool:
        """Check patterns and deliver at most one suggestion. Returns True
        iff a suggestion was delivered (any outcome)."""
        if not self._config.enabled:
            return False
        command = self._pick_candidate(now)
        if command is None:
            return False
        # A command in flight wins; the candidate stays eligible next tick.
        if not self._begin_session():
            return False
        try:
            outcome = self._deliver(command)
            self._store.log_suggestion(command, now.hour, outcome)
        finally:
            self._end_session()
        return True

    def _pick_candidate(self, now: datetime) -> str | None:
        entries = self._store.get_patterns().get(
            "hourly_commands", {}).get(str(now.hour))
        if not entries:
            return None

        # Global cooldown — ANY outcome burns the hourly budget, so silence
        # can't cause nagging. All time math keys off `now` so tick() is
        # deterministic under test.
        now_utc = now.astimezone(timezone.utc)
        last = self._store.last_suggestion_at()
        if last:
            last_dt = datetime.fromisoformat(last)
            if now_utc - last_dt < timedelta(minutes=self._config.cooldown_min):
                return None

        today = now.strftime("%Y-%m-%d")
        recent_cutoff = (now_utc - timedelta(
            minutes=self._config.recent_run_suppress_min)).isoformat()
        for command, day_count in entries:
            if day_count < self._config.min_pattern_days:
                continue
            if self._store.suggestion_declined_on(command, today):
                continue
            if self._store.command_seen_since(command, recent_cutoff):
                continue
            return command
        return None

    def _deliver(self, command: str) -> str:
        self._set_hud("set_transcript", f"제안: {command}")
        self._set_hud("set_state", "processing")
        self._speak(f"이 시간대에 보통 '{command}'라고 하시는데, 지금 할까요?")
        self._set_hud("set_state", "listening")

        try:
            answer = _parse_answer(self._listen())
        except Exception as e:
            print(f"[Suggest] listen failed: {e}", file=sys.stderr)
            answer = None

        if answer is True:
            self._speak("네, 바로 할게요.")
            self._run_command(command)
            return "accepted"

        self._set_hud("set_transcript", "")
        self._set_hud("set_state", "idle")
        if answer is False:
            self._speak("알겠어요. 오늘은 다시 제안하지 않을게요.")
            return "declined"
        return "timeout"

    def _set_hud(self, method: str, arg) -> None:
        if self._hud is None:
            return
        try:
            getattr(self._hud, method)(arg)
        except Exception:
            pass
