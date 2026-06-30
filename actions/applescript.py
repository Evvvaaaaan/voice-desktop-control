import subprocess


def run_applescript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return f"error: {result.stderr.strip()}"
    return result.stdout.strip()
