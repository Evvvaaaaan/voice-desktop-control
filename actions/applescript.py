import subprocess


def run_applescript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()
