from actions.applescript import run_applescript
from actions.mouse_keyboard import click, type_text, press_key, scroll
from actions.screen import take_screenshot


def dispatch(action: str, params: dict) -> str:
    if action == "launch_app":
        app = params.get("app", "")
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
    else:
        return f"unknown_action:{action}"
