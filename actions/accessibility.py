import subprocess


def click_element_by_name(app_name: str, element_name: str) -> bool:
    script = f'''
    tell application "{app_name}"
        activate
    end tell
    tell application "System Events"
        tell process "{app_name}"
            click button "{element_name}" of window 1
        end tell
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False
