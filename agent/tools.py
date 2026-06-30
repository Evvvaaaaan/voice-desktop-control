import re
from actions.applescript import run_applescript
from actions.mouse_keyboard import click, type_text, press_key, scroll
from actions.screen import take_screenshot

_SAFE_APP_NAME = re.compile(r'^[A-Za-z0-9 ._-]+$')


class _DispatchExecutor:
    def run(self, action: str, params: dict) -> bool:
        return bool(dispatch(action, params))


def dispatch(action: str, params: dict) -> str:
    if action == "launch_app":
        app = params.get("app", "")
        if not _SAFE_APP_NAME.match(app):
            return f"error: invalid app name: {app}"
        return run_applescript(f'tell application "{app}" to activate')
    elif action == "click":
        click(params["x"], params["y"])
        return "clicked"
    elif action == "type_text":
        type_text(params["text"])
        return "typed"
    elif action == "press_key":
        press_key(params["key"])
        return "pressed"
    elif action == "scroll":
        scroll(params.get("x", 0), params.get("y", 0),
               params.get("direction", "down"), params.get("amount", 3))
        return "scrolled"
    elif action == "run_applescript":
        return run_applescript(params["script"])
    elif action == "screenshot":
        return f"screenshot_taken:{len(take_screenshot())} bytes"
    elif action == "speak_only":
        return ""
    elif action == "run_routine":
        from routines.manager import RoutineManager
        mgr = RoutineManager("data/routines.json")
        name = params.get("name", "")
        success = mgr.execute(name, _DispatchExecutor())
        return "routine_done" if success else "routine_failed"
    else:
        return f"unknown_action:{action}"
