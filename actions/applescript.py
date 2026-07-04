# actions/applescript.py
import subprocess


def run_applescript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=False, timeout=30
    )
    stdout = result.stdout
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    stderr = result.stderr
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
        
    if result.returncode != 0:
        return f"error: {stderr.strip()}"
    return stdout.strip()
