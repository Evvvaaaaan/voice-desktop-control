import subprocess
import time

import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

# Smooth, human-visible cursor travel (computer-use style) rather than an
# instant jump — the pointer glides to the target before acting.
_MOVE_DURATION = 0.45
_TWEEN = pyautogui.easeInOutQuad

# Time to let the UI react (menu opens, page transitions, hover states)
# before the agent's next screenshot. Without this, a click followed
# immediately by an observation screenshot often captures a mid-animation
# frame, which reads to the model as "nothing happened" and causes retries
# or duplicate clicks.
_SETTLE_SEC = 0.35


def move_mouse(x: int, y: int, duration: float = _MOVE_DURATION) -> None:
    pyautogui.moveTo(x, y, duration=duration, tween=_TWEEN)


def click(x: int, y: int, duration: float = _MOVE_DURATION) -> None:
    # Glide to the target first so the movement is visible, then click.
    pyautogui.moveTo(x, y, duration=duration, tween=_TWEEN)
    pyautogui.click()
    time.sleep(_SETTLE_SEC)


def double_click(x: int, y: int, duration: float = _MOVE_DURATION) -> None:
    pyautogui.moveTo(x, y, duration=duration, tween=_TWEEN)
    pyautogui.doubleClick()
    time.sleep(_SETTLE_SEC)


def type_text(text: str) -> None:
    # pyautogui.typewrite silently drops non-ASCII (e.g. Korean), so route
    # anything non-ASCII through the clipboard + Cmd+V instead.
    if text.isascii():
        pyautogui.typewrite(text, interval=0.05)
        return
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    pyautogui.hotkey("command", "v")


def press_key(key: str) -> None:
    # "cmd+t" style combos must go through hotkey(); press() only handles
    # single keys and silently no-ops on unknown names.
    parts = [p.strip() for p in key.split("+") if p.strip()]
    alias = {"cmd": "command", "opt": "option", "control": "ctrl", "return": "enter"}
    parts = [alias.get(p.lower(), p.lower()) for p in parts]
    if len(parts) > 1:
        pyautogui.hotkey(*parts)
    elif parts:
        pyautogui.press(parts[0])


def scroll(x, y, direction: str, amount: int = 3) -> None:
    clicks = amount if direction == "up" else -amount
    # Only reposition the pointer when an explicit target is given; passing
    # (0, 0) would fling the cursor to the corner and trip the failsafe.
    if x or y:
        pyautogui.scroll(clicks, x=x, y=y)
    else:
        pyautogui.scroll(clicks)
